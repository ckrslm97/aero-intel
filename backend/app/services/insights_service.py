"""Deterministic pattern detection over the news archive for the /insights page.

Every aggregate here is computed from data the pipeline already stores --
articles, enrichments, entity links -- so the page costs nothing to render and
its numbers can be traced back to rows. The only LLM involvement is the daily
digest paragraph (build_daily_digest), one call per day, stored in
insight_digests.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.config import get_settings
from app.data import airport, country_name
from app.core.logging import get_logger
from app.hubs import HUBS
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.insight import InsightDigest

logger = get_logger(__name__)


async def category_volume_by_week(db: AsyncSession, weeks: int = 8) -> dict:
    """Article counts per category per ISO week. No longer part of the
    /insights payload (the page dropped its volume chart) -- kept because the
    daily digest prompt still feeds on these numbers."""
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    # One shared expression for SELECT and GROUP BY -- Postgres treats
    # to_char(date_trunc(x)) and date_trunc(x) as different expressions and
    # rejects the mismatch.
    week_expr = func.to_char(func.date_trunc("week", Article.published_at), "YYYY-MM-DD")
    rows = (
        await db.execute(
            select(week_expr, ArticleEnrichment.category, func.count())
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .where(Article.is_duplicate.is_(False), Article.published_at >= since)
            .group_by(week_expr, ArticleEnrichment.category)
        )
    ).all()

    week_labels = sorted({week for week, _, _ in rows})
    totals: dict[str, int] = {}
    for _, category, count in rows:
        totals[category] = totals.get(category, 0) + count
    top_categories = [c for c, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:6]]

    series = {
        category: [0] * len(week_labels) for category in top_categories
    }
    index = {week: i for i, week in enumerate(week_labels)}
    for week, category, count in rows:
        if category in series:
            series[category][index[week]] = count
    return {"weeks": week_labels, "series": series}


async def airline_momentum(db: AsyncSession, window_days: int = 7, limit: int = 10) -> list[dict]:
    """Which airlines the news is suddenly about: mention counts in the last
    `window_days` vs the window before it."""
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=2 * window_days)

    async def _counts(start: datetime, end: datetime) -> dict[str, tuple[str, int]]:
        rows = (
            await db.execute(
                select(Entity.code, Entity.name, func.count())
                .join(ArticleEntity, ArticleEntity.entity_id == Entity.id)
                .join(Article, Article.id == ArticleEntity.article_id)
                .where(
                    Entity.entity_type == "airline",
                    Article.is_duplicate.is_(False),
                    Article.published_at >= start,
                    Article.published_at < end,
                )
                .group_by(Entity.code, Entity.name)
            )
        ).all()
        return {code or name: (name, count) for code, name, count in rows}

    current = await _counts(current_start, now)
    previous = await _counts(previous_start, current_start)

    movers = []
    for key in set(current) | set(previous):
        name = (current.get(key) or previous.get(key))[0]
        cur = current.get(key, (name, 0))[1]
        prev = previous.get(key, (name, 0))[1]
        movers.append(
            {"code": key, "name": name, "current": cur, "previous": prev, "delta": cur - prev}
        )
    movers.sort(key=lambda m: (-abs(m["delta"]), -m["current"]))
    return movers[:limit]


# How many airports a single route signal may claim. A launch announcement
# names its destination and usually its origin; anything past the third is
# almost always a comparison ("unlike its LHR and CDG services"), and on the
# map every extra code becomes a marker a reader will read as a destination.
MAX_SIGNAL_AIRPORTS = 3


def _destination_airports(airports: list[dict], airlines: list[str]) -> list[dict]:
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


async def new_route_signals(
    db: AsyncSession, days: int = 30, per_region: int = 6, max_articles: int = 120
) -> list[dict]:
    """New-route announcements grouped by world region, with the articles
    behind each count. The insights page renders these as a cited list --
    every signal links back to its source -- so this returns article detail,
    not bare counts. `count` is the full regional total even when the article
    list is capped at `per_region`."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(Article, ArticleEnrichment)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            # defer: only headlines and links are rendered, but the full scraped
            # bodies were being pulled out of Postgres for every match.
            .options(selectinload(Article.source), defer(Article.raw_content))
            .where(
                Article.is_duplicate.is_(False),
                Article.published_at >= since,
                ArticleEnrichment.category == "network",
                ArticleEnrichment.subcategory == "new_route",
            )
            .order_by(Article.published_at.desc().nulls_last())
            # The page shows at most `per_region` per region across ~9 regions;
            # an unbounded fetch was reading the whole month of route news.
            .limit(max_articles)
        )
    ).all()

    article_ids = [article.id for article, _ in rows]
    airlines_by_article: dict = {}
    airports_by_article: dict = {}
    if article_ids:
        # Airlines and airports in one round trip rather than two: the page
        # needs both for every signal ("which carrier, into which airport"),
        # and they live in the same join.
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
                    ArticleEntity.article_id.in_(article_ids),
                    Entity.entity_type.in_(("airline", "airport")),
                )
            )
        ).all()
        for article_id, entity_type, code, name in entity_rows:
            if entity_type == "airline":
                airlines_by_article.setdefault(article_id, []).append(code or name)
                continue
            # Coordinates and city come from the bundled reference data
            # (app/data), not from the entity row -- the entity table stores
            # only what the extractor saw in the text. An airport the dataset
            # does not know is dropped rather than emitted without a position:
            # the map would have nowhere to put it.
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
    for article, enrichment in rows:
        airlines = airlines_by_article.get(article.id, [])
        grouped.setdefault(enrichment.region, []).append(
            {
                "id": str(article.id),
                "headline": enrichment.headline_tr or enrichment.headline or article.title,
                "url": article.url,
                "source_name": article.source.name if article.source else "",
                "published_at": (
                    article.published_at.isoformat() if article.published_at else None
                ),
                "airlines": airlines,
                "airports": _destination_airports(
                    airports_by_article.get(article.id, []), airlines
                ),
            }
        )
    return [
        {"region": region, "count": len(articles), "articles": articles[:per_region]}
        for region, articles in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]


async def sentiment_by_category(db: AsyncSession, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(ArticleEnrichment.category, ArticleEnrichment.sentiment, func.count())
            .join(Article, Article.id == ArticleEnrichment.article_id)
            .where(Article.is_duplicate.is_(False), Article.published_at >= since)
            .group_by(ArticleEnrichment.category, ArticleEnrichment.sentiment)
        )
    ).all()
    by_category: dict[str, dict[str, int]] = {}
    for category, sentiment, count in rows:
        by_category.setdefault(category, {"positive": 0, "neutral": 0, "negative": 0})
        if sentiment in by_category[category]:
            by_category[category][sentiment] = count
    return [
        {"category": category, **counts}
        for category, counts in sorted(
            by_category.items(), key=lambda kv: -(sum(kv[1].values()))
        )
    ]


async def latest_digest(db: AsyncSession, topic: str = "daily") -> InsightDigest | None:
    return (
        await db.execute(
            select(InsightDigest)
            .where(InsightDigest.topic == topic)
            .order_by(InsightDigest.digest_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _fallback_digest(movers: list[dict], routes: list[dict]) -> str:
    """Deterministic Turkish summary when no LLM is configured -- honest,
    template-shaped, still grounded in the same numbers."""
    parts = []
    rising = [m for m in movers if m["delta"] > 0][:3]
    if rising:
        parts.append(
            "Bu hafta gündemi yükselenler: "
            + ", ".join(f"{m['name']} ({m['previous']}→{m['current']} haber)" for m in rising)
            + "."
        )
    if routes:
        top = routes[0]
        region = top["region"] or "küresel"
        parts.append(f"Yeni hat duyurularının en yoğun olduğu bölge: {region} ({top['count']} haber).")
    return " ".join(parts) or "Bu hafta belirgin bir örüntü öne çıkmadı."


async def build_daily_digest(db: AsyncSession) -> InsightDigest:
    """Compute today's aggregates, have the strong model write one Turkish
    paragraph about the pattern, store it (one row per day, upserted)."""
    movers = await airline_momentum(db)
    # Compact per-region counts only -- the digest prompt doesn't need the
    # article detail the insights page renders.
    routes = [
        {"region": r["region"], "count": r["count"]} for r in await new_route_signals(db)
    ]
    volume = await category_volume_by_week(db, weeks=4)

    provider_name = "heuristic"
    body: str | None = None
    settings = get_settings()
    if settings.llm_provider == "openai_compat" and settings.llm_base_url:
        from app.llm.openai_compat import OpenAICompatProvider

        stats = (
            f"Havayolu momentum (son 7 gün vs önceki 7 gün): {movers[:6]}. "
            f"Bölgelere göre yeni hat duyuruları (30 gün): {routes}. "
            f"Haftalık kategori hacimleri: {volume['series']}."
        )
        prompt = (
            "Sen bir havacılık istihbarat analistisin. Aşağıdaki istatistiklerden "
            "TEK paragraflık (3-4 cümle) Türkçe bir 'günün örüntüsü' özeti yaz. "
            "Sayı uydurma; yalnız verilen verilere dayan. İstatistikler: " + stats
        )
        try:
            live = OpenAICompatProvider(
                settings.llm_base_url, settings.llm_model, settings.llm_api_key
            )
            body = (await live._generate(prompt)).strip()  # noqa: SLF001 -- deliberate: bespoke prompt, not a pipeline task
            provider_name = "openai_compat"
        except Exception as exc:  # noqa: BLE001 -- digest must not crash the job
            logger.warning("digest_llm_failed_falling_back", error=str(exc))
            body = None
    if not body:
        body = _fallback_digest(movers, routes)
        provider_name = "heuristic"

    today = datetime.now(timezone.utc).date()
    existing = (
        await db.execute(
            select(InsightDigest).where(
                InsightDigest.digest_date == today, InsightDigest.topic == "daily"
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = InsightDigest(
            digest_date=today, topic="daily", body=body, provider=provider_name
        )
        db.add(existing)
    else:
        existing.body = body
        existing.provider = provider_name
    await db.commit()
    logger.info("insight_digest_built", provider=provider_name, chars=len(body))
    return existing
