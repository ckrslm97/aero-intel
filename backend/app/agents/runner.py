"""The v2 pipeline: gate -> cluster -> classify -> confidence -> news_events.

Runs entirely on top of v1, not instead of it. It selects articles v1 has
already ingested and enriched (`status == "enriched"`) and that no event has
claimed yet (`event_id is None`), and it never writes `status` or touches
`article_enrichment`. v1's queries filter on `status`, so nothing this module
does changes what v1 sees or does -- see docs/ARCHITECTURE.md's rollout note
and app/core/config.py's `pipeline_v2` flag.

Stages, per batch:

1. **Cluster candidates** -- build one `EventCandidate` per article from its
   title and the entities v1's heuristic already extracted (no LLM spent on
   this; see pipeline/clustering.py for why entity overlap plus a shared
   distinctive token, not a similarity threshold, is what decides a match).
2. **Pick a primary** per cluster (highest source tier, earliest publication)
   and run the *cheap, local* checks against it before spending a model call:
   language (pipeline/language.py) and the aviation-relevance gate
   (agents/gate.py). A cluster that fails either is recorded and dropped --
   no classification call is made for it.
3. **Classify** the primary with the one consolidated call
   (llm/classify.classify_article). Its outcome is a tri-state per field (see
   pipeline/outcomes.py): CLASSIFIED, NOT_APPLICABLE ("not a risk" is a real,
   durable answer), or FAILED (never published, retried on a later run).
4. **Score confidence** (pipeline/confidence.py) from source tier, the
   classifier's own certainty, field completeness, and cluster size. A record
   below the medium band is written but `is_published=False` -- the low band
   is the audit trail of what this run chose not to show, not a bug.
5. **Persist** one `NewsEvent` per surviving cluster, link every member
   article to it via `Article.event_id`, and, when the classifier called the
   event a campaign, hand it to `agents/campaign_airline.py` for a second
   validation pass and a `Promotion` row. Campaign rules live in that module,
   not here, because "is this a usable campaign" is a different question from
   "is this a usable event" with its own required fields and its own guards
   (an expired title, an implausible sale window) -- this runner only calls
   it at the right point and persists what it returns.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.campaign_airline import build_promotion, validate_campaign
from app.agents.gate import evaluate as gate_evaluate
from app.core.logging import get_logger
from app.llm.classify import classify_article
from app.llm.gazetteer import COUNTRY_ALIASES, fold_for_match
from app.models.article import Article
from app.models.entity import ArticleEntity
from app.models.news_event import NewsEvent
from app.pipeline.clustering import EventCandidate, cluster, pick_primary
from app.pipeline.confidence import ConfidenceInput, is_publishable, score
from app.pipeline.language import resolve as resolve_language
from app.pipeline.outcomes import OutcomeState
from app.pipeline.risk_scoring import score as score_risk
from app.taxonomy import COUNTRY_TO_REGION, risk_category_family_of

logger = get_logger(__name__)

#: How far back to pull candidates. Wide enough that a follow-up report on an
#: event from a few days ago still has something to cluster against; narrow
#: enough that one run stays cheap. Mirrors pipeline/dedup.py's own window.
LOOKBACK_WINDOW_DAYS = 3
DEFAULT_BATCH_SIZE = 40

#: Fields that must be present before an event can leave the low band. Kept
#: here rather than imported from confidence.py because *what counts as
#: complete* is a domain decision (news vs. campaign vs. risk each have their
#: own answer), not something the scoring module should know about.
REQUIRED_NEWS_FIELDS = ("title_tr", "summary_tr", "category")


def _tier_for_trust_weight(weight: float) -> str:
    """Bridge from the continuous 0-1 `Source.trust_weight` to the five
    discrete tiers pipeline/confidence.py scores against.

    Provisional: the source ladder in Faz 5's plan gives every seeded source
    an explicit tier (`agents.base.SourceSpec.tier`); until sources_seed.py is
    rewritten to carry one, this bucketing is the honest approximation. No
    seeded source currently reaches 1.0, so "official" is never produced here
    -- that tier is reserved for sources this bridge cannot see, like a
    campaign page scraped directly from an airline's own domain.
    """
    if weight >= 0.90:
        return "regulator"
    if weight >= 0.75:
        return "agency"
    if weight >= 0.50:
        return "trade"
    return "aggregator"


def _slugify(title: str, article_id) -> str:
    ascii_title = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:160]
    # The article id suffix is what guarantees uniqueness -- two stories that
    # stem to the same slug text (rare, but "thy-yeni-hat" is generic) must
    # still get distinct rows.
    return f"{slug or 'olay'}-{str(article_id)[:8]}"


def _entity_codes(article: Article) -> frozenset[str]:
    """Subject entities for clustering, reusing v1's heuristic extraction
    rather than spending a model call before we even know if this article
    clears the gate."""
    codes: set[str] = set()
    for link in article.entity_links:
        entity = link.entity
        if entity is None:
            continue
        if entity.code:
            codes.add(entity.code.upper())
        elif entity.entity_type == "country" and entity.name:
            codes.add(entity.name.upper())
    return frozenset(codes)


@dataclass
class RunStats:
    candidates: int = 0
    events: int = 0
    published: int = 0
    campaigns: int = 0
    rejected_language: int = 0
    rejected_gate: int = 0
    not_relevant: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "events": self.events,
            "published": self.published,
            "campaigns": self.campaigns,
            "rejected_language": self.rejected_language,
            "rejected_gate": self.rejected_gate,
            "not_relevant": self.not_relevant,
            "failed": self.failed,
        }


async def _fetch_candidates(db: AsyncSession, limit: int) -> list[Article]:
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_WINDOW_DAYS)
    result = await db.execute(
        select(Article)
        .options(
            selectinload(Article.source),
            selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
        )
        .where(
            Article.status == "enriched",
            Article.event_id.is_(None),
            Article.is_duplicate.is_(False),
            Article.fetched_at >= since,
        )
        .order_by(Article.fetched_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique().all())


def _confidence_for(classification, certainty: float | None, tier: str, source_count: int):
    present = sum(
        1
        for field in REQUIRED_NEWS_FIELDS
        if getattr(classification, field, None)
    )
    return score(
        ConfidenceInput(
            source_tier=tier,
            classifier_certainty=certainty,
            required_fields_present=present,
            required_fields_total=len(REQUIRED_NEWS_FIELDS),
            # No independent deterministic cross-check is wired yet -- that is
            # the gate's keyword signal compared against the model's category,
            # a refinement for a later pass. None reads as neutral, not as
            # disagreement; see pipeline/confidence.py.
            signal_agreement=None,
            source_count=source_count,
        )
    )


def _canonical_country(country: str | None) -> str | None:
    """The model answers in whichever language it was writing the rest of the
    response in -- "Russia" and "Rusya" both happen. Route through the same
    gazetteer alias table entity extraction uses (which now carries the
    Turkish country names, see llm/gazetteer.py) rather than a bare lowercase
    match against COUNTRY_TO_REGION's English-only keys, which would silently
    fail on every Turkish answer.
    """
    if not country:
        return None
    return COUNTRY_ALIASES.get(fold_for_match(country))


def _region_for(country: str | None) -> str | None:
    canonical = _canonical_country(country)
    if not canonical:
        return None
    return COUNTRY_TO_REGION.get(canonical)


async def run_pipeline_v2(db: AsyncSession, *, limit: int = DEFAULT_BATCH_SIZE) -> dict:
    """Process up to `limit` unclustered, already-enriched articles.

    Safe to call with `settings.pipeline_v2` unset -- the caller (the CLI
    command) is what gates on the flag, this function has no opinion about it.
    That keeps the function directly testable without monkeypatching settings.
    """
    stats = RunStats()
    articles = await _fetch_candidates(db, limit)
    stats.candidates = len(articles)
    if not articles:
        return stats.as_dict()

    by_id = {a.id: a for a in articles}
    candidates = [
        EventCandidate(
            article_id=a.id,
            title=a.title,
            entities=_entity_codes(a),
            tier=_tier_for_trust_weight(a.source.trust_weight if a.source else 0.5),
            published_at=(a.published_at or a.fetched_at).isoformat(),
        )
        for a in articles
    ]

    now = datetime.now(timezone.utc)

    for group in cluster(candidates):
        primary_candidate = pick_primary(group)
        primary = by_id[primary_candidate.article_id]
        members = [by_id[c.article_id] for c in group]

        verdict = resolve_language(primary.title, primary.raw_content)
        for member in members:
            member.language = verdict.language
        if not verdict.is_supported:
            for member in members:
                member.rejection_reason = verdict.rejection_reason
            stats.rejected_language += 1
            continue

        gate_result = gate_evaluate(primary.title, primary.raw_content)
        if not gate_result.passed:
            for member in members:
                member.rejection_reason = f"gate:{gate_result.reason}"
            stats.rejected_gate += 1
            continue

        result = await classify_article(primary.title, primary.raw_content)

        if result.article.state is OutcomeState.FAILED:
            for member in members:
                member.rejection_reason = f"classify_failed:{result.article.reason}"
            stats.failed += 1
            continue

        if result.article.state is OutcomeState.NOT_APPLICABLE:
            for member in members:
                member.rejection_reason = f"not_relevant:{result.article.reason}"
            stats.not_relevant += 1
            continue

        classification = result.article.payload
        confidence = _confidence_for(
            classification, result.article.certainty, primary_candidate.tier, len(members)
        )

        not_applicable: dict = {}
        risk_type = risk_family = risk_severity = risk_country = risk_city = None
        risk_score_value = None
        risk_assessed_at = None
        if result.risk.state is not OutcomeState.FAILED:
            risk_assessed_at = now
            if result.risk.state is OutcomeState.CLASSIFIED:
                risk = result.risk.payload
                risk_type = risk.category
                risk_family = risk_category_family_of(risk.category)
                risk_severity = risk.severity
                risk_country = _canonical_country(risk.country) or risk.country
                risk_city = risk.city
                risk_score_value = score_risk(
                    severity=risk.severity,
                    probability=risk.probability,
                    aviation_impact_score=risk.aviation_impact_score,
                    source_tier=primary_candidate.tier,
                    event_time=primary.published_at or primary.fetched_at,
                    now=now,
                ).score
            else:
                not_applicable["risk"] = result.risk.reason

        # A second validation layer on top of the model's own "is this a
        # campaign" verdict: agents/campaign_airline.py catches the
        # expired-title and implausible-sale-window patterns that were still
        # reaching production after the model-level fix. It only ever narrows
        # a CLASSIFIED verdict to NOT_APPLICABLE, never the reverse.
        campaign_to_persist = None
        if result.campaign.state is OutcomeState.CLASSIFIED:
            campaign_verdict = validate_campaign(
                primary.title, result.campaign.payload, today=now.date()
            )
            if campaign_verdict.is_classified:
                campaign_to_persist = campaign_verdict.payload
            else:
                not_applicable["campaign"] = campaign_verdict.reason
        elif result.campaign.state is OutcomeState.NOT_APPLICABLE:
            not_applicable["campaign"] = result.campaign.reason

        region = _region_for(risk_country) or _region_for(
            classification.countries[0] if classification.countries else None
        )

        event = NewsEvent(
            slug=_slugify(classification.title_tr or primary.title, primary.id),
            title_tr=classification.title_tr,
            summary_tr=classification.summary_tr,
            primary_article_id=primary.id,
            category=classification.category,
            subcategory=classification.subcategory,
            region=region,
            risk_type=risk_type,
            risk_family=risk_family,
            risk_severity=risk_severity,
            risk_country=risk_country,
            risk_city=risk_city,
            risk_score=risk_score_value,
            risk_assessed_at=risk_assessed_at,
            confidence_score=confidence.score,
            confidence_band=confidence.band,
            confidence_detail=confidence.as_detail(),
            not_applicable_reasons=not_applicable or None,
            first_seen=min((m.published_at or m.fetched_at) for m in members),
            last_seen=max((m.published_at or m.fetched_at) for m in members),
            article_count=len(members),
            is_published=is_publishable(confidence.band),
        )

        # Captured before the savepoint, not read from `primary` after: a
        # rollback expires every instance touched inside the block, and
        # reading an expired attribute triggers an implicit reload that
        # SQLAlchemy's asyncio mode cannot do outside an active greenlet --
        # caught by this test suite as a MissingGreenlet masking the real
        # IntegrityError underneath it.
        primary_url = primary.url

        # Each cluster writes inside its own savepoint, the same discipline
        # pipeline/enrich.py uses for the same reason: `promotions.url` is
        # unique, and a rare collision (this article already produced a
        # promotion in an earlier run that crashed after insert but before
        # commit, or a concurrent run) must cost this one cluster, not the
        # rest of the batch.
        wrote_campaign = False
        try:
            async with db.begin_nested():
                db.add(event)
                await db.flush()  # need event.id before linking members

                for member in members:
                    member.event_id = event.id

                if campaign_to_persist is not None:
                    promotion = build_promotion(
                        event=event,
                        primary=primary,
                        campaign=campaign_to_persist,
                        certainty=result.campaign.certainty,
                        source_tier=primary_candidate.tier,
                        source_count=len(members),
                        detected_at=now,
                    )
                    db.add(promotion)
                    wrote_campaign = True
        except IntegrityError:
            logger.info("pipeline_v2_cluster_collision", primary_article_url=primary_url)
            stats.failed += 1
            continue

        stats.events += 1
        if wrote_campaign:
            stats.campaigns += 1
        if event.is_published:
            stats.published += 1

    await db.commit()
    logger.info("pipeline_v2_run_complete", **stats.as_dict())
    return stats.as_dict()
