"""New-route announcements for the Hub page's Ağ Sinyalleri tab, the Sinyaller
feed, /biz -- and the daily digest.

The count is taken over news_events (pipeline v2) rather than over raw
articles: classification happens once per event (see app/models/news_event.py),
so a route signal that three outlets reported is one signal, not three. The
article-based version that used to live in insights_service.new_route_signals
counted the duplicate reporting, and it is gone -- while both existed, İçgörüler
and the Hub page put two different numbers on the same real-world event, and an
analyst reading İçgörüler saw competitor network activity overstated by however
many outlets happened to pick the story up.

Airport resolution uses the app.data.airport() lookup against the full
3,241-airport reference table -- not the ~20-entry app.hubs.HUBS list, which
only names the carriers this desk actively watches and was never meant as a
general-purpose gazetteer.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.data import airport, country_name
from app.hubs import HUBS
from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent


# How many airports a single route signal may claim. A launch announcement
# names its destination and usually its origin; anything past the third is
# almost always a comparison ("unlike its LHR and CDG services"), and on the
# map every extra code becomes a marker a reader will read as a destination.
MAX_SIGNAL_AIRPORTS = 3


def destination_airports(airports: list[dict], airlines: list[str]) -> list[dict]:
    """The airports a signal is actually *about*.

    Two corrections to the raw extraction, both aimed at the map:

    * A carrier's own hub is the origin, not a new destination. An article
      naming TK and IST is not announcing a new route to Istanbul. The
      carrier->hub mapping is derived from `app/hubs.py`, which already
      records which carriers are based at each hub, rather than restated
      here where the two could drift.
    * Order is text order, so the first codes are the ones the headline
      named; comparisons trail. Keeping the first few is a better guess at
      "the destination" than keeping all of them.

    Origins are only dropped when something survives them -- a signal whose
    every airport is a hub still shows those, because an empty list would
    silently erase the story from the map.
    """
    if not airports:
        return []
    codes = {code.upper() for code in airlines if code}
    origins = {
        hub.code
        for hub in HUBS
        if any(carrier.upper() in codes for carrier in hub.carriers)
    }
    destinations = [a for a in airports if a["code"] not in origins]
    return (destinations or airports)[:MAX_SIGNAL_AIRPORTS]


async def network_signals(
    db: AsyncSession,
    days: int = 30,
    per_region: int = 6,
    max_events: int = 120,
    now: datetime | None = None,
) -> list[dict]:
    """New-route events grouped by world region, with the primary article
    behind each one. Every signal links back to its source, so this returns
    article detail rather than bare counts; `count` is the full regional total
    even when the listed articles are capped at `per_region`.

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
