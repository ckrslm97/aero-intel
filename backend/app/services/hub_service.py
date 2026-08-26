"""What the archive knows about each hub.

The facts (city, coordinates, based carriers) come from app/hubs.py; everything
else here is counted from articles already ingested. Nothing is estimated: a
hub with no coverage returns zero rather than a plausible-looking number, and
the page says so.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.data import airport
from app.hubs import HUBS, HUBS_BY_CODE, Hub
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion

# Read endpoints only ever serve these two bands -- see confidence.py. A
# fabricated-looking Hub tab is worse than a thin one.
PUBLISHABLE_BANDS = ("high", "medium")

# How many co-mentions before a pair of airports is drawn as a line. One shared
# article is a coincidence -- a wire story listing six destinations links them
# all to each other without any of them being a route.
MIN_ROUTE_MENTIONS = 2


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _hub_payload(hub: Hub) -> dict:
    return {
        "code": hub.code,
        "name": hub.name,
        "city": hub.city,
        "country": hub.country,
        "region": hub.region,
        "lat": hub.lat,
        "lon": hub.lon,
        "carriers": list(hub.carriers),
        "note_tr": hub.note_tr,
    }


async def _mention_counts(db: AsyncSession, days: int) -> dict[str, int]:
    """Articles per airport code. One query, not one per hub."""
    result = await db.execute(
        select(Entity.code, func.count(func.distinct(ArticleEntity.article_id)))
        .join(ArticleEntity, ArticleEntity.entity_id == Entity.id)
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(
            Entity.entity_type == "airport",
            Article.is_duplicate.is_(False),
            func.coalesce(Article.published_at, Article.fetched_at) >= _since(days),
        )
        .group_by(Entity.code)
    )
    return {code: count for code, count in result.all() if code}


async def _routes(db: AsyncSession, days: int) -> list[dict]:
    """Airport pairs that keep turning up in the same story.

    This is a co-mention graph, not a schedule. We have no OAG feed on the free
    tier, so a "line" here means the archive keeps discussing these two places
    together -- which is the honest claim the map makes.

    Both ends resolve against the full 3,241-airport reference table
    (app.data.airport), not HUBS_BY_CODE. HUBS_BY_CODE only names the ~20
    hubs this desk actively watches, so resolving against it silently dropped
    any pair where either end was a real, mentioned airport this desk simply
    doesn't track a carrier at -- the map lost most of its lines to airports
    it had never heard of, not to airports that don't exist.
    """
    left_link = aliased(ArticleEntity)
    right_link = aliased(ArticleEntity)
    left = aliased(Entity)
    right = aliased(Entity)

    result = await db.execute(
        select(left.code, right.code, func.count(func.distinct(left_link.article_id)))
        .select_from(left_link)
        .join(left, and_(left.id == left_link.entity_id, left.entity_type == "airport"))
        .join(right_link, right_link.article_id == left_link.article_id)
        .join(right, and_(right.id == right_link.entity_id, right.entity_type == "airport"))
        .join(Article, Article.id == left_link.article_id)
        .where(
            # Ordered pair, so A-B and B-A collapse into one line.
            left.code < right.code,
            Article.is_duplicate.is_(False),
            func.coalesce(Article.published_at, Article.fetched_at) >= _since(days),
        )
        .group_by(left.code, right.code)
        .having(func.count(func.distinct(left_link.article_id)) >= MIN_ROUTE_MENTIONS)
        .order_by(func.count(func.distinct(left_link.article_id)).desc())
        .limit(40)
    )

    routes = []
    for from_code, to_code, count in result.all():
        origin, destination = airport(from_code), airport(to_code)
        # Both ends need coordinates or there is no line to draw.
        if origin is None or destination is None:
            continue
        routes.append(
            {
                "from": from_code,
                "to": to_code,
                "from_lat": origin.lat, "from_lon": origin.lon,
                "to_lat": destination.lat, "to_lon": destination.lon,
                "article_count": count,
            }
        )
    return routes


def _event_payload(event: NewsEvent) -> dict:
    return {
        "id": str(event.id),
        "slug": event.slug,
        "headline": event.title_tr,
        "category": event.category,
        "confidence_band": event.confidence_band,
        "last_seen": event.last_seen.isoformat(),
    }


async def _hub_events(db: AsyncSession, hub: Hub, days: int) -> list[dict]:
    """Pipeline-v2 events whose primary article names this airport --
    everything the old article-mention count above rolls up, but as citable
    rows rather than a bare number."""
    mentions = (
        select(ArticleEntity.article_id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(Entity.entity_type == "airport", Entity.code == hub.code)
    )
    rows = (
        await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.primary_article_id.in_(mentions),
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.last_seen >= _since(days),
            )
            .order_by(NewsEvent.last_seen.desc())
            .limit(20)
        )
    ).scalars().all()
    return [_event_payload(e) for e in rows]


async def _hub_risks(db: AsyncSession, hub: Hub, days: int) -> list[dict]:
    """Risk events in this hub's country -- risk_country is stored lowercase
    (see app/agents/runner.py._canonical_country), so the match is too."""
    rows = (
        await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.risk_country == hub.country.lower(),
                NewsEvent.risk_type.is_not(None),
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.last_seen >= _since(days),
            )
            .order_by(NewsEvent.risk_score.desc().nulls_last())
            .limit(20)
        )
    ).scalars().all()
    return [
        {
            **_event_payload(e),
            "risk_type": e.risk_type,
            "risk_family": e.risk_family,
            "risk_severity": e.risk_severity,
            "risk_score": e.risk_score,
        }
        for e in rows
    ]


async def _hub_campaigns(db: AsyncSession, hub: Hub, days: int) -> list[dict]:
    """Campaigns touching this hub's market. `markets_json`'s country/city
    lists are the precise match; `region` is the fallback for the campaigns
    the agent hasn't (yet) populated markets_json for -- see Promotion's own
    docstring on why the two coexist."""
    rows = (
        await db.execute(
            select(Promotion)
            .where(
                Promotion.confidence_band.in_(PUBLISHABLE_BANDS),
                Promotion.superseded_at.is_(None),
                Promotion.detected_at >= _since(days),
                or_(
                    Promotion.region == hub.region,
                    Promotion.markets_json["countries"].op("?")(hub.country),
                    Promotion.markets_json["cities"].op("?")(hub.city),
                ),
            )
            .order_by(Promotion.detected_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [
        {
            "id": str(p.id),
            "airline_code": p.airline_code,
            "airline_name": p.airline_name,
            "title": p.title_tr,
            "discount_pct": p.discount_pct,
            "sale_starts": p.sale_starts.isoformat() if p.sale_starts else None,
            "sale_ends": p.sale_ends.isoformat() if p.sale_ends else None,
            "confidence_band": p.confidence_band,
            "url": p.url,
        }
        for p in rows
    ]


async def hub_overview(db: AsyncSession, days: int = 30) -> dict:
    counts = await _mention_counts(db, days)
    hubs = [{**_hub_payload(hub), "article_count": counts.get(hub.code, 0)} for hub in HUBS]
    hubs.sort(key=lambda h: (-h["article_count"], h["code"]))
    return {"days": days, "hubs": hubs, "routes": await _routes(db, days)}


async def hub_detail(db: AsyncSession, code: str, days: int = 90) -> dict | None:
    hub = HUBS_BY_CODE.get(code.upper())
    if hub is None:
        return None

    mentions = (
        select(ArticleEntity.article_id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(Entity.entity_type == "airport", Entity.code == hub.code)
    )
    in_window = and_(
        Article.is_duplicate.is_(False),
        Article.id.in_(mentions),
        func.coalesce(Article.published_at, Article.fetched_at) >= _since(days),
    )

    total = (
        await db.execute(select(func.count(Article.id)).select_from(Article).where(in_window))
    ).scalar_one()

    by_category = (
        await db.execute(
            select(ArticleEnrichment.category, func.count(Article.id))
            .select_from(Article)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .where(in_window)
            .group_by(ArticleEnrichment.category)
            .order_by(func.count(Article.id).desc())
        )
    ).all()

    # Which carriers the coverage of this airport is actually about -- often not
    # the ones based there, which is itself worth seeing.
    carriers = (
        await db.execute(
            select(Entity.code, Entity.name, func.count(func.distinct(Article.id)))
            .select_from(Article)
            .join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(in_window, Entity.entity_type == "airline")
            .group_by(Entity.code, Entity.name)
            .order_by(func.count(func.distinct(Article.id)).desc())
            .limit(8)
        )
    ).all()

    events, risks, campaigns = (
        await _hub_events(db, hub, days),
        await _hub_risks(db, hub, days),
        await _hub_campaigns(db, hub, days),
    )

    return {
        **_hub_payload(hub),
        "days": days,
        "article_count": total,
        "categories": [{"slug": slug, "count": count} for slug, count in by_category],
        # Deliberately NOT "carriers": that key already holds the airlines based
        # here (from _hub_payload) and a second one would silently overwrite it.
        # The two are different questions, and the gap between them is the
        # interesting part -- coverage of a hub is often about a visiting
        # carrier, not a resident one.
        "carriers_seen": [
            {"code": code, "name": name, "article_count": count}
            for code, name, count in carriers
        ],
        # Pipeline-v2 composition (K9/Faz 10): events, risks and campaigns
        # touching this hub, each a citable row rather than a bare count.
        "events": events,
        "risks": risks,
        "campaigns": campaigns,
    }
