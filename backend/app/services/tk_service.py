"""Aggregations over the agent-curated Turkish Airlines passenger reviews for
the BİZ page, plus the one-off 70b synthesis paragraph.

Everything except build_tk_digest is deterministic and computed in Python: the
whole table is at curation scale (tens of rows), so a single SELECT and a pass
over the rows beats maintaining five GROUP BY queries.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.insight import InsightDigest
from app.models.tk_review import REVIEW_THEMES, TkReview
from app.services.insights_service import latest_digest

logger = get_logger(__name__)

TK_DIGEST_TOPIC = "tk_reviews"


def _quote_dict(review: TkReview) -> dict:
    return {
        "excerpt": review.excerpt_tr or review.excerpt,
        "original": review.excerpt if review.excerpt_tr else None,
        "url": review.url,
        "source_name": review.source_name,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "rating": review.rating,
        "sentiment": review.sentiment,
        "route": review.route,
        "author": review.author,
        "themes": list(review.themes or []),
    }


async def review_stats(db: AsyncSession, quote_limit: int = 12) -> dict:
    """The full BİZ-page aggregate: rating summary, sentiment split, theme
    breakdown (each with a sample quote), source mix, and recent quotes."""
    reviews = (
        (
            await db.execute(
                select(TkReview).order_by(TkReview.review_date.desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )

    rated = [r.rating for r in reviews if r.rating is not None]
    sentiment = {"positive": 0, "neutral": 0, "negative": 0}
    sources: dict[str, int] = {}
    theme_counts: dict[str, dict] = {
        slug: {"count": 0, "positive": 0, "negative": 0, "quote": None}
        for slug in REVIEW_THEMES
    }

    for review in reviews:
        if review.sentiment in sentiment:
            sentiment[review.sentiment] += 1
        sources[review.source_name] = sources.get(review.source_name, 0) + 1
        for slug in review.themes or []:
            bucket = theme_counts.get(slug)
            if bucket is None:
                continue  # unknown tag in seed data -- skip rather than crash
            bucket["count"] += 1
            if review.sentiment == "positive":
                bucket["positive"] += 1
            elif review.sentiment == "negative":
                bucket["negative"] += 1
            # Reviews arrive newest-first, so the first quote per theme is the
            # most recent one -- prefer a Turkish excerpt when present.
            if bucket["quote"] is None and (review.excerpt_tr or review.excerpt):
                bucket["quote"] = _quote_dict(review)

    themes = [
        {"slug": slug, "label": REVIEW_THEMES[slug], **data}
        for slug, data in theme_counts.items()
        if data["count"] > 0
    ]
    themes.sort(key=lambda t: -t["count"])

    return {
        "review_count": len(reviews),
        "rating": {
            "average": round(sum(rated) / len(rated), 1) if rated else None,
            "count": len(rated),
        },
        "sentiment": sentiment,
        "themes": themes,
        "sources": [
            {"name": name, "count": count}
            for name, count in sorted(sources.items(), key=lambda kv: -kv[1])
        ],
        "quotes": [_quote_dict(r) for r in reviews[:quote_limit]],
    }


def _fallback_tk_digest(stats: dict) -> str:
    parts = []
    avg = stats["rating"]["average"]
    if avg is not None:
        parts.append(
            f"Toplanan {stats['review_count']} yorumda ortalama puan 10 üzerinden {avg}."
        )
    top = stats["themes"][:3]
    if top:
        parts.append(
            "En çok konuşulan temalar: " + ", ".join(t["label"] for t in top) + "."
        )
    neg = [t for t in stats["themes"] if t["negative"] > t["positive"]]
    if neg:
        parts.append("Şikayetlerin yoğunlaştığı alan: " + neg[0]["label"] + ".")
    return " ".join(parts) or "Henüz analiz edilecek yorum toplanmadı."


async def build_tk_digest(db: AsyncSession) -> InsightDigest:
    """One 70b call: a Turkish synthesis of what passengers are saying about
    TK, stored like the daily insight digest (one row per day, upserted)."""
    stats = await review_stats(db)

    provider_name = "heuristic"
    body: str | None = None
    settings = get_settings()
    if settings.llm_provider == "openai_compat" and settings.llm_base_url and stats["review_count"]:
        from app.llm.openai_compat import OpenAICompatProvider

        theme_lines = "; ".join(
            f"{t['label']}: {t['count']} yorum ({t['positive']}+ / {t['negative']}-)"
            for t in stats["themes"]
        )
        prompt = (
            "Sen Türk Hava Yolları için çalışan bir müşteri deneyimi analistisin. "
            "Aşağıdaki, halka açık sitelerden toplanmış yolcu yorumu istatistiklerinden "
            "2 kısa paragraflık Türkçe bir sentez yaz: önce genel tablo (puan, duygu dengesi), "
            "sonra öne çıkan güçlü/zayıf temalar. Sayı uydurma; yalnız verilen verilere dayan. "
            f"Yorum sayısı: {stats['review_count']}. "
            f"Ortalama puan (10 üzerinden): {stats['rating']['average']}. "
            f"Duygu: {stats['sentiment']}. Temalar: {theme_lines}."
        )
        try:
            live = OpenAICompatProvider(
                settings.llm_base_url, settings.llm_model, settings.llm_api_key
            )
            body = (await live._generate(prompt)).strip()  # noqa: SLF001 -- deliberate: bespoke prompt, not a pipeline task
            provider_name = "openai_compat"
        except Exception as exc:  # noqa: BLE001 -- synthesis must not crash the seed job
            logger.warning("tk_digest_llm_failed_falling_back", error=str(exc))
            body = None
    if not body:
        body = _fallback_tk_digest(stats)
        provider_name = "heuristic"

    today = datetime.now(timezone.utc).date()
    existing = (
        await db.execute(
            select(InsightDigest).where(
                InsightDigest.digest_date == today, InsightDigest.topic == TK_DIGEST_TOPIC
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = InsightDigest(
            digest_date=today, topic=TK_DIGEST_TOPIC, body=body, provider=provider_name
        )
        db.add(existing)
    else:
        existing.body = body
        existing.provider = provider_name
    await db.commit()
    logger.info("tk_digest_built", provider=provider_name, chars=len(body))
    return existing


async def latest_tk_digest(db: AsyncSession) -> InsightDigest | None:
    return await latest_digest(db, topic=TK_DIGEST_TOPIC)
