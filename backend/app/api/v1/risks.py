"""Risk Radarı: natural-disaster and conflict signals classified out of the
news feed, grouped by country.

Grouping and ranking are done here rather than in the browser on purpose. The
page draws the same set three ways -- a map, a "Sıcak Noktalar" ranking and a
country-sectioned list -- and all three must agree on which country is worst.
Computing the weighted score once, server-side, is what guarantees that; three
client-side re-derivations of it would be three chances to disagree.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.logging import get_logger
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.clustering import EventCandidate, cluster, entity_codes, pick_primary, tier_for_source
from app.taxonomy import (
    COUNTRY_TO_REGION,
    RISK_SEVERITY_WEIGHT,
    RISK_TYPE_FAMILY,
    RISK_TYPE_LABELS_TR,
)

router = APIRouter(prefix="/risks", tags=["risks"])
logger = get_logger(__name__)


class RiskItemOut(BaseModel):
    id: str
    headline: str
    url: str
    source_name: str
    published_at: datetime | None
    risk_type: str
    risk_family: str
    risk_type_label_tr: str
    severity: str
    country: str | None
    city: str | None
    region: str | None
    # Whether the story broke in the last 24h. Computed here so the page shows
    # a quiet "son 24 saat" tag without every card re-deriving the cutoff (and
    # without a flash animation -- this is a disaster feed, not a notification).
    is_fresh: bool
    # How many articles cluster()'d into this one card. 1 for the common case;
    # >1 means multiple outlets reported the same event and this is already
    # the merged, reconciled view -- see list_risks()'s clustering pass.
    source_count: int = 1


class SeverityCountsOut(BaseModel):
    high: int
    medium: int
    low: int


class RiskCountryOut(BaseModel):
    country: str
    region: str | None
    count: int
    # high=3, medium=2, low=1, summed. The one number the map, the ranking and
    # the list all sort by.
    score: int
    severity_counts: SeverityCountsOut
    items: list[RiskItemOut]


class RiskRadarOut(BaseModel):
    days: int
    total: int
    countries: list[RiskCountryOut]
    # Feed-wide totals per type/family, so the filter chips can show counts
    # without the client flattening every group to count them.
    type_counts: dict[str, int]
    family_counts: dict[str, int]


# Rows whose country never resolved still belong on the page -- the event is
# real, only its placement is unknown -- so they are grouped under this label
# rather than dropped. The map skips them (there is no centroid for "unknown");
# the list shows them last.
UNKNOWN_COUNTRY = "Belirtilmemiş"

FRESH_WINDOW = timedelta(hours=24)


@router.get("", response_model=RiskRadarOut)
async def list_risks(
    days: int = Query(14, ge=1, le=90),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> RiskRadarOut:
    """Every classified risk event in the window, grouped by country and sorted
    by weighted severity score."""
    # AGGREGATES, not ARTICLES: this is a grouped rollup like /insights and
    # /hubs, not a raw article list, and it changes only when the enrichment
    # cron reclassifies something.
    public_cache(response, AGGREGATES)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    result = await db.execute(
        select(Article)
        .options(
            selectinload(Article.source),
            selectinload(Article.enrichment),
            selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
        )
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            Article.is_duplicate.is_(False),
            ArticleEnrichment.risk_type.is_not(None),
            Article.published_at.is_not(None),
            Article.published_at >= since,
        )
        .order_by(Article.published_at.desc())
    )
    articles = [
        a
        for a in result.scalars().unique().all()
        if a.enrichment is not None and a.enrichment.risk_type is not None
    ]

    grouped: dict[str, list[RiskItemOut]] = {}
    type_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}

    # Three outlets covering one eruption used to be three cards, independently
    # classified, and they could disagree on severity and even on which
    # country it happened in (a passing "ash also reached Malta" aside once
    # outranked a correctly-resolved Catania/Italy in a sibling article). One
    # cluster, one card: reuse the same entity-overlap + distinctive-token
    # clustering v2 uses for news_events (app/pipeline/clustering.py) rather
    # than inventing a second, Risk-Radarı-specific notion of "same event".
    by_id = {a.id: a for a in articles}
    candidates = [
        EventCandidate(
            article_id=a.id,
            title=a.title,
            entities=entity_codes(a),
            tier=tier_for_source(a.source),
            published_at=a.published_at.isoformat() if a.published_at else None,
        )
        for a in articles
    ]

    for group in cluster(candidates):
        members = [by_id[c.article_id] for c in group]
        primary = by_id[pick_primary(group).article_id]
        primary_enrichment = primary.enrichment

        if len(members) > 1:
            logger.info(
                "risk_cluster_membership_debug",
                size=len(members),
                titles=[m.title[:60] for m in members],
                ids=[str(m.id) for m in members],
            )

        # Severity: the most severe member wins. A vaguer report that never
        # mentions the closure's scale should not water down one that does --
        # under-stating a live hazard is the wrong failure mode here.
        severity = max(
            (m.enrichment.risk_severity or "low" for m in members),
            key=lambda s: RISK_SEVERITY_WEIGHT.get(s, 1),
        )

        # Country/city: prefer whichever member actually resolved a city --
        # that is real evidence (a named airport or landmark), not an
        # incidental mention -- over one that only ever produced a bare
        # country, and over the primary's own placement if a better one
        # exists elsewhere in the cluster. Earliest member first among ties,
        # matching pick_primary's own "first telling" preference.
        by_published = sorted(members, key=lambda m: m.published_at or now)
        city_bearer = next((m for m in by_published if m.enrichment.risk_city), None)
        country_bearer = city_bearer or next(
            (m for m in by_published if m.enrichment.risk_country), None
        )
        risk_country = country_bearer.enrichment.risk_country if country_bearer else None
        risk_city = city_bearer.enrichment.risk_city if city_bearer else None
        country = risk_country or UNKNOWN_COUNTRY

        # Risk type: the most-agreed-on classification; primary's own call
        # breaks a tie, since it is the highest-tier/earliest telling.
        type_votes: dict[str, int] = {}
        for m in members:
            type_votes[m.enrichment.risk_type] = type_votes.get(m.enrichment.risk_type, 0) + 1
        risk_type = max(
            type_votes,
            key=lambda t: (type_votes[t], t == primary_enrichment.risk_type),
        )
        family = (
            primary_enrichment.risk_family
            if primary_enrichment.risk_type == risk_type
            else None
        ) or RISK_TYPE_FAMILY.get(risk_type)
        if family is None:
            continue

        published = primary.published_at
        item = RiskItemOut(
            id=str(primary.id),
            headline=primary_enrichment.headline_tr or primary_enrichment.headline or primary.title,
            url=primary.url,
            source_name=primary.source.name if primary.source else "",
            published_at=published,
            risk_type=risk_type,
            risk_family=family,
            risk_type_label_tr=RISK_TYPE_LABELS_TR.get(risk_type, risk_type),
            severity=severity,
            country=risk_country,
            city=risk_city,
            region=(country_bearer.enrichment.region if country_bearer else None)
            or COUNTRY_TO_REGION.get(country.lower()),
            is_fresh=bool(published and (now - published) <= FRESH_WINDOW),
            source_count=len(members),
        )
        grouped.setdefault(country, []).append(item)
        type_counts[risk_type] = type_counts.get(risk_type, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1

    countries: list[RiskCountryOut] = []
    for country, items in grouped.items():
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in items:
            if item.severity in counts:
                counts[item.severity] += 1
        score = sum(RISK_SEVERITY_WEIGHT.get(i.severity, 1) for i in items)
        countries.append(
            RiskCountryOut(
                country=country,
                region=COUNTRY_TO_REGION.get(country.lower()),
                count=len(items),
                score=score,
                severity_counts=SeverityCountsOut(**counts),
                # Within a country, worst first -- then newest. A reader
                # scanning a country section should meet its worst event first.
                items=sorted(
                    items,
                    key=lambda i: (
                        -RISK_SEVERITY_WEIGHT.get(i.severity, 1),
                        -(i.published_at.timestamp() if i.published_at else 0),
                    ),
                ),
            )
        )

    # Score desc, then count desc, then name -- a stable order the ranking and
    # the list can both rely on. The unplaced bucket sorts last regardless of
    # its score: it is a data-quality residue, not the worst-hit country.
    countries.sort(
        key=lambda c: (c.country == UNKNOWN_COUNTRY, -c.score, -c.count, c.country)
    )

    return RiskRadarOut(
        days=days,
        # Signals shown, not articles scanned: with clustering, the same
        # eruption reported by three outlets is one signal, not three, and
        # the page's own "X / Y sinyal" counter needs Y to be a number X can
        # actually reach.
        total=sum(len(items) for items in grouped.values()),
        countries=countries,
        type_counts=type_counts,
        family_counts=family_counts,
    )
