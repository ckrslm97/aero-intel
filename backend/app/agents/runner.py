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
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.classify import classify_article
from app.llm.classify_prompt import campaign_topic_fragment
from app.llm.gazetteer import COUNTRY_ALIASES, fold_for_match
from app.llm.heuristic import RETROSPECTIVE_REASON, is_retrospective
from app.models.article import Article
from app.models.entity import ArticleEntity
from app.models.news_event import NewsEvent
from app.pipeline.clustering import EventCandidate, cluster, entity_codes, pick_primary, tier_for_source
from app.pipeline.confidence import ConfidenceInput, is_publishable, score
from app.pipeline.language import resolve as resolve_language
from app.pipeline.outcomes import Outcome, OutcomeState
from app.pipeline.promo_dedup import (
    campaign_tier_for_article,
    candidate_from_row,
    ensure_source_row,
    find_duplicate,
    merge_candidate,
    record_version,
    rescore_for_corroboration,
)
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


def _slugify(title: str, article_id) -> str:
    ascii_title = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:160]
    # The article id suffix is what guarantees uniqueness -- two stories that
    # stem to the same slug text (rare, but "thy-yeni-hat" is generic) must
    # still get distinct rows.
    return f"{slug or 'olay'}-{str(article_id)[:8]}"


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


#: The campaign-intelligence columns an article-derived row can fill on a row
#: that already exists. Null-never-overwrites, the same rule promo_dedup applies
#: to the columns it knows about: a row classified from the carrier's own page
#: must not be re-labelled by a news report that happens to arrive later.
_V2_MERGE_COLUMNS: tuple[str, ...] = (
    "campaign_type",
    "business_class",
    "classification_reason",
    "route_scope",
    "ond",
    "origin_code",
    "dest_code",
    "route_json",
)


#: Of those, the ones a version row should carry. The route JSON is excluded
#: for the same reason campaign_extract excludes its blobs: nobody reads two
#: nested dicts as a diff.
_VERSIONED_V2_COLUMNS = tuple(c for c in _V2_MERGE_COLUMNS if c != "route_json")


def _fill_missing_campaign_fields(row, incoming) -> dict[str, dict]:
    """Fill the v2 columns this row is missing; return what that changed."""
    row.last_seen_at = incoming.last_seen_at or row.last_seen_at
    if row.first_seen_at is None:
        row.first_seen_at = incoming.first_seen_at
    changed: dict[str, dict] = {}
    for column in _V2_MERGE_COLUMNS:
        value = getattr(incoming, column, None)
        if value is not None and getattr(row, column) is None:
            setattr(row, column, value)
            if column in _VERSIONED_V2_COLUMNS:
                changed[column] = {"previous": None, "new": value}
    return changed


def apply_campaign_intelligence(
    promotion, campaign, details: dict, *, text: str, now: datetime
) -> None:
    """Fill the campaign-intelligence columns on an article-derived row.

    The deep-scan path gets these from the extraction chain; the article path
    gets what the consolidated prompt's campaign fragment returned, run through
    the *same* route resolver (pipeline/campaign_extract.resolve_route) so a
    campaign found in a news report and the same campaign found on the
    carrier's page describe their route identically instead of in two dialects.

    No evidence_json: an article path has no per-field quotes to cite, and an
    empty citation map would read as "checked, nothing found" rather than "not
    asked for". Confidence stays exactly what build_promotion computed --
    nothing here is new evidence about how sure we are.
    """
    from app.pipeline.campaign_extract import resolve_route

    route = resolve_route(campaign.origin, campaign.destination, text=text)

    promotion.campaign_type = campaign.campaign_type
    # The rule layer's verdict outranks the model's hint: `details` is
    # validate_campaign's answer, which has already looked at the rulepacks.
    promotion.business_class = details.get("business_class") or campaign.business_class_hint
    promotion.classification_reason = details.get("classification_reason")
    promotion.route_scope = route.scope
    promotion.ond = route.ond
    promotion.origin_code = route.origin_code
    promotion.dest_code = route.dest_code
    promotion.route_json = route.as_json()
    promotion.first_seen_at = now
    promotion.last_seen_at = now


async def run_pipeline_v2(db: AsyncSession, *, limit: int = DEFAULT_BATCH_SIZE) -> dict:
    """Process up to `limit` unclustered, already-enriched articles.

    Safe to call with `settings.pipeline_v2` unset -- the caller (the CLI
    command) is what gates on the flag, this function has no opinion about it.
    That keeps the function directly testable without monkeypatching settings.
    """
    stats = RunStats()
    # Read once per run, not per cluster: a flag that could change mid-batch
    # would give two clusters in the same run two different behaviours.
    campaign_v2 = get_settings().campaign_v2_enabled
    articles = await _fetch_candidates(db, limit)
    stats.candidates = len(articles)
    if not articles:
        return stats.as_dict()

    by_id = {a.id: a for a in articles}
    candidates = [
        EventCandidate(
            article_id=a.id,
            title=a.title,
            entities=entity_codes(a),
            tier=tier_for_source(a.source),
            published_at=(a.published_at or a.fetched_at).isoformat(),
        )
        for a in articles
    ]

    now = datetime.now(timezone.utc)

    for group in cluster(candidates):
        primary_candidate = pick_primary(group)
        primary = by_id[primary_candidate.article_id]
        members = [by_id[c.article_id] for c in group]

        # The source's own declared language, when it has one -- see
        # pipeline/language.py for why a human's claim about a feed beats a
        # detector working on a six-word headline, and why detection still
        # runs as the safety net for mixed or undeclared sources.
        declared_language = primary.source.language if primary.source else None
        verdict = resolve_language(primary.title, primary.raw_content, declared=declared_language)
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

        result = await classify_article(
            primary.title,
            primary.raw_content,
            # Empty string when the flag is off, which is the parameter's own
            # default -- the prompt is then byte-for-byte the one the golden
            # set grades.
            topic_fragment=campaign_topic_fragment() if campaign_v2 else "",
        )

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
        risk_score_detail = None
        aviation_impact_note = None
        risk_assessed_at = None
        # A second validation layer over the model's own "is this a risk"
        # verdict, the same shape as the campaign one below: it can only ever
        # narrow. An anniversary piece is a real disaster told years after the
        # fact, and nothing in this pipeline carries an event date -- only the
        # publication time, which would put a 2023 earthquake on today's radar.
        # See app/llm/heuristic.py's RETROSPECTIVE GUARD.
        risk_outcome = result.risk
        if risk_outcome.state is OutcomeState.CLASSIFIED and is_retrospective(primary.title):
            risk_outcome = Outcome.not_applicable(
                RETROSPECTIVE_REASON, certainty=risk_outcome.certainty
            )

        if risk_outcome.state is not OutcomeState.FAILED:
            risk_assessed_at = now
            if risk_outcome.state is OutcomeState.CLASSIFIED:
                risk = risk_outcome.payload
                risk_type = risk.category
                risk_family = risk_category_family_of(risk.category)
                risk_severity = risk.severity
                risk_country = _canonical_country(risk.country) or risk.country
                risk_city = risk.city
                # `.score` used to be read straight off the call and the rest of
                # the result dropped. A risk score is the product of five
                # factors, so a bare 0.08 says nothing about WHICH of the five
                # collapsed it -- keep the breakdown, the same way
                # confidence_detail keeps the confidence ladder's.
                risk_score = score_risk(
                    severity=risk.severity,
                    probability=risk.probability,
                    aviation_impact_score=risk.aviation_impact_score,
                    source_tier=primary_candidate.tier,
                    event_time=primary.published_at or primary.fetched_at,
                    now=now,
                )
                risk_score_value = risk_score.score
                risk_score_detail = risk_score.components
                # The model's own sentence for why aviation cares. Parsed since
                # v2 shipped, stored from here on: it is the only human-readable
                # half of aviation_impact_score, and re-deriving it later would
                # cost another model call on an article we no longer keep.
                aviation_impact_note = risk.aviation_impact_note
            else:
                not_applicable["risk"] = risk_outcome.reason

        # A second validation layer on top of the model's own "is this a
        # campaign" verdict: agents/campaign_airline.py catches the
        # expired-title and implausible-sale-window patterns that were still
        # reaching production after the model-level fix. It only ever narrows
        # a CLASSIFIED verdict to NOT_APPLICABLE, never the reverse.
        campaign_to_persist = None
        campaign_details: dict = {}
        if result.campaign.state is OutcomeState.CLASSIFIED:
            campaign_verdict = validate_campaign(
                primary.title, result.campaign.payload, today=now.date()
            )
            campaign_details = campaign_verdict.details
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
            risk_score_detail=risk_score_detail,
            aviation_impact_note=aviation_impact_note,
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
                    # What this article counts as, as a campaign source. An
                    # article is secondary reporting about somebody else's
                    # campaign; only a source that IS the carrier ranks above
                    # that -- see promo_dedup.ARTICLE_TIER_TO_CAMPAIGN_TIER.
                    article_tier = campaign_tier_for_article(primary_candidate.tier)
                    merged_into = None
                    if campaign_v2:
                        apply_campaign_intelligence(
                            promotion,
                            campaign_to_persist,
                            campaign_details,
                            text=f"{primary.title}\n{primary.raw_content or ''}",
                            now=now,
                        )
                        # The documented gap in this path, closed: every other
                        # write path asks promo_dedup before inserting, and
                        # this one did not -- so the airline's own campaign
                        # page and a news report about the same campaign each
                        # drew their own bar on the timeline. Merging keeps the
                        # older row (and its detected_at, which the "Yeni"
                        # badge reads) and folds this reading into it.
                        candidate = candidate_from_row(promotion)
                        candidate.source_tier = article_tier
                        duplicate = await find_duplicate(db, candidate)
                        if duplicate is not None:
                            displaced_url = duplicate.url
                            displaced_source = duplicate.source_name
                            changed = merge_candidate(duplicate, candidate)
                            changed.update(
                                _fill_missing_campaign_fields(duplicate, promotion)
                            )
                            await db.flush()
                            # The incumbent's own page and this article both go
                            # on the record; the row is then re-scored for the
                            # corroboration it just gained.
                            await ensure_source_row(
                                db,
                                duplicate,
                                url=displaced_url,
                                source_name=displaced_source,
                                seen_at=duplicate.first_seen_at or duplicate.detected_at,
                            )
                            await ensure_source_row(
                                db,
                                duplicate,
                                url=promotion.url,
                                source_name=promotion.source_name,
                                tier=article_tier,
                                seen_at=now,
                                page_published_at=(
                                    primary.published_at.date()
                                    if primary.published_at
                                    else None
                                ),
                            )
                            await rescore_for_corroboration(db, duplicate)
                            await record_version(
                                db, duplicate, changed, source_url=promotion.url, now=now
                            )
                            merged_into = duplicate
                            logger.info(
                                "pipeline_v2_campaign_merged",
                                airline=candidate.airline_code,
                                kept_id=str(duplicate.id),
                                incoming_url=candidate.url,
                            )
                        else:
                            db.add(promotion)
                    else:
                        db.add(promotion)

                    if merged_into is None:
                        # N>=1 for the row this run created. Unconditional,
                        # like the rest of the provenance bookkeeping: it
                        # changes nothing about what `promotions` holds or what
                        # the API serves, and a v1 row with no recorded source
                        # would be a hole in the invariant for no gain.
                        await db.flush()
                        await ensure_source_row(
                            db,
                            promotion,
                            url=promotion.url,
                            source_name=promotion.source_name,
                            tier=article_tier,
                            seen_at=now,
                            page_published_at=(
                                primary.published_at.date() if primary.published_at else None
                            ),
                        )
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
