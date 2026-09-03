"""New-route announcements for the Hub page's Ağ Sinyalleri tab.

This is insights_service.new_route_signals()'s logic moved onto news_events
(pipeline v2) instead of raw articles -- classification now happens once per
event rather than once per article (see app/models/news_event.py), and a
route signal citing a duplicate-reporting article three times over was never
the honest count. insights_service.new_route_signals itself is left exactly
as it is: it still backs the live İçgörüler page's route section, and that
page is not being switched to v2 in this change (see K8/K9 in the rebuild
plan -- one page's route flips per PR, and İçgörüler's hasn't yet).

Airport resolution reuses the same app.data.airport() lookup against the full
3,241-airport reference table that insights_service already uses -- not the
~20-entry app.hubs.HUBS list, which only names the carriers this desk
actively watches and was never meant as a general-purpose gazetteer.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.data import airport, country_name
from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.services.insights_service import destination_airports


async def network_signals(
    db: AsyncSession,
    days: int = 30,
    per_region: int = 6,
    max_events: int = 120,
    now: datetime | None = None,
) -> list[dict]:
    """New-route events grouped by world region, with the primary article
    behind each one -- the same cited-list contract as the v1 version.

    `now` is the window's anchor, passed in by a caller that has to state the
    window it served (/hubs/network-signals' envelope, and /biz, which cuts
    four sections to one instant). Defaulted, so nothing else changes.
    """
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    events = (
        await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.category == "network",
                NewsEvent.subcategory == "new_route",
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(("high", "medium")),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.last_seen >= since,
            )
            .order_by(NewsEvent.last_seen.desc())
            .limit(max_events)
        )
    ).scalars().all()

    primary_ids = [e.primary_article_id for e in events if e.primary_article_id]
    articles_by_id: dict = {}
    if primary_ids:
        article_rows = (
            await db.execute(
                select(Article)
                .options(selectinload(Article.source), defer(Article.raw_content))
                .where(Article.id.in_(primary_ids))
            )
        ).scalars().all()
        articles_by_id = {a.id: a for a in article_rows}

    airlines_by_article: dict = {}
    airports_by_article: dict = {}
    if primary_ids:
        entity_rows = (
            await db.execute(
                select(
                    ArticleEntity.article_id,
                    Entity.entity_type,
                    Entity.code,
                    Entity.name,
                )
                .join(Entity, Entity.id == ArticleEntity.entity_id)
                .where(
                    ArticleEntity.article_id.in_(primary_ids),
                    Entity.entity_type.in_(("airline", "airport")),
                )
            )
        ).all()
        for article_id, entity_type, code, name in entity_rows:
            if entity_type == "airline":
                airlines_by_article.setdefault(article_id, []).append(code or name)
                continue
            entry = airport(code)
            if entry is None:
                continue
            seen = airports_by_article.setdefault(article_id, [])
            if any(a["code"] == entry.iata for a in seen):
                continue
            seen.append(
                {
                    "code": entry.iata,
                    "name": entry.name,
                    "city": entry.city or entry.name,
                    "country": country_name(entry.country) or entry.country,
                    "lat": entry.lat,
                    "lon": entry.lon,
                }
            )

    grouped: dict[str | None, list[dict]] = {}
    for event in events:
        article = articles_by_id.get(event.primary_article_id)
        if article is None:
            # No citable source -- an uncited signal is worse than a missing one.
            continue
        airlines = airlines_by_article.get(article.id, [])
        grouped.setdefault(event.region, []).append(
            {
                "id": str(event.id),
                "slug": event.slug,
                "headline": event.title_tr or article.title,
                "url": article.url,
                "source_name": article.source.name if article.source else "",
                "published_at": event.first_seen.isoformat() if event.first_seen else None,
                "article_count": event.article_count,
                "airlines": airlines,
                "airports": destination_airports(
                    airports_by_article.get(article.id, []), airlines
                ),
            }
        )

    return [
        {"region": region, "count": len(items), "articles": items[:per_region]}
        for region, items in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]
