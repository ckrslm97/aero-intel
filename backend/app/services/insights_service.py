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

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.insight import InsightDigest

logger = get_logger(__name__)


async def category_volume_by_week(db: AsyncSession, weeks: int = 8) -> dict:
    """Article counts per category per ISO week -- the 'what is the news about
    lately' trendline."""
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


async def new_route_signals(db: AsyncSession, days: int = 30) -> list[dict]:
    """New-route announcements by world region -- where networks are growing."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(ArticleEnrichment.region, func.count())
            .join(Article, Article.id == ArticleEnrichment.article_id)
            .where(
                Article.is_duplicate.is_(False),
                Article.published_at >= since,
                ArticleEnrichment.category == "network",
                ArticleEnrichment.subcategory == "new_route",
            )
            .group_by(ArticleEnrichment.region)
            .order_by(func.count().desc())
        )
    ).all()
    return [{"region": region, "count": count} for region, count in rows]


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


async def top_corroborated_stories(db: AsyncSession, days: int = 14, limit: int = 5) -> list[dict]:
    """The most independently-confirmed stories -- the week's hard signal."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(Article, ArticleEnrichment)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .where(
                Article.is_duplicate.is_(False),
                Article.published_at >= since,
                ArticleEnrichment.corroborating_source_count > 1,
            )
            .order_by(
                ArticleEnrichment.corroborating_source_count.desc(),
                ArticleEnrichment.confidence_score.desc(),
            )
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(article.id),
            "headline": enrichment.headline_tr or enrichment.headline or article.title,
            "url": article.url,
            "sources": enrichment.corroborating_source_count,
            "category": enrichment.category,
        }
        for article, enrichment in rows
    ]


async def latest_digest(db: AsyncSession) -> InsightDigest | None:
    return (
        await db.execute(select(InsightDigest).order_by(InsightDigest.digest_date.desc()).limit(1))
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
    routes = await new_route_signals(db)
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
        await db.execute(select(InsightDigest).where(InsightDigest.digest_date == today))
    ).scalar_one_or_none()
    if existing is None:
        existing = InsightDigest(digest_date=today, body=body, provider=provider_name)
        db.add(existing)
    else:
        existing.body = body
        existing.provider = provider_name
    await db.commit()
    logger.info("insight_digest_built", provider=provider_name, chars=len(body))
    return existing
