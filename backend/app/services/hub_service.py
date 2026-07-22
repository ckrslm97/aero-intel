"""What the archive knows about each hub.

The facts (city, coordinates, based carriers) come from app/hubs.py; everything
else here is counted from articles already ingested. Nothing is estimated: a
hub with no coverage returns zero rather than a plausible-looking number, and
the page says so.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.hubs import HUBS, HUBS_BY_CODE, Hub
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity

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
        origin, destination = HUBS_BY_CODE.get(from_code), HUBS_BY_CODE.get(to_code)
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

    return {
        **_hub_payload(hub),
        "days": days,
        "article_count": total,
        "categories": [{"slug": slug, "count": count} for slug, count in by_category],
        "carriers": [
            {"code": code, "name": name, "article_count": count}
            for code, name, count in carriers
        ],
    }
