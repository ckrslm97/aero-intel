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
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.taxonomy import (
    COUNTRY_TO_REGION,
    RISK_SEVERITY_WEIGHT,
    RISK_TYPE_FAMILY,
    RISK_TYPE_LABELS_TR,
)

router = APIRouter(prefix="/risks", tags=["risks"])


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
        .options(selectinload(Article.source), selectinload(Article.enrichment))
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            Article.is_duplicate.is_(False),
            ArticleEnrichment.risk_type.is_not(None),
            Article.published_at.is_not(None),
            Article.published_at >= since,
        )
        .order_by(Article.published_at.desc())
    )
    articles = list(result.scalars().unique().all())

    grouped: dict[str, list[RiskItemOut]] = {}
    type_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}

    for article in articles:
        enrichment = article.enrichment
        if enrichment is None or enrichment.risk_type is None:
            continue
        risk_type = enrichment.risk_type
        # risk_family is written through app.taxonomy.risk_family_of(), but a
        # row backfilled by an older revision could still carry null -- derive
        # it rather than emitting a family the response model would reject.
        family = enrichment.risk_family or RISK_TYPE_FAMILY.get(risk_type)
        if family is None:
            continue
        severity = enrichment.risk_severity or "low"
        country = enrichment.risk_country or UNKNOWN_COUNTRY

        published = article.published_at
        item = RiskItemOut(
            id=str(article.id),
            headline=enrichment.headline_tr or enrichment.headline or article.title,
            url=article.url,
            source_name=article.source.name if article.source else "",
            published_at=published,
            risk_type=risk_type,
            risk_family=family,
            risk_type_label_tr=RISK_TYPE_LABELS_TR.get(risk_type, risk_type),
            severity=severity,
            country=enrichment.risk_country,
            city=enrichment.risk_city,
            region=enrichment.region or COUNTRY_TO_REGION.get(country.lower()),
            is_fresh=bool(published and (now - published) <= FRESH_WINDOW),
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
        total=len(articles),
        countries=countries,
        type_counts=type_counts,
        family_counts=family_counts,
    )
