"""AI enrichment: headline, summary, category, sentiment, entities, and
cross-source confidence for every deduped (canonical) article.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.factory import get_llm_provider
from app.llm.heuristic import detect_region
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.search_indexing import index_article_text
from app.pipeline.verify import compute_confidence
from app.repositories.entity_repository import EntityRepository

logger = get_logger(__name__)


def _importance_score(confidence: float, corroborating_count: int) -> float:
    """More corroborating independent sources -> higher importance; this is what
    the Top-10 story board (M3) ranks by."""
    return round(min(1.0, confidence * 0.7 + min(corroborating_count, 5) * 0.06), 3)


async def enrich_pending_articles(db: AsyncSession, limit: int | None = None) -> int:
    """Enrich every deduped article, or the freshest `limit` of them.

    A limit exists so a single scheduled run can't blow the LLM's daily budget
    (see app/core/config.py llm_enrich_batch_size). When capped we take the most
    recently published first -- that's what a reader opening the site wants
    translated soonest; the backlog is picked up over subsequent runs. The
    heuristic path passes no limit (it's free and instant).
    """
    provider = get_llm_provider()
    entity_repo = EntityRepository(db)

    query = select(Article).where(Article.status == "deduped")
    if limit is not None:
        query = query.order_by(Article.published_at.desc().nulls_last()).limit(limit)
    result = await db.execute(query)
    articles = list(result.scalars().all())

    for article in articles:
        headline = await provider.generate_headline(article.title, article.raw_content)
        summary = await provider.generate_summary(article.title, article.raw_content)
        category = await provider.categorize(article.title, article.raw_content)
        sentiment = await provider.sentiment(article.title, article.raw_content)
        entities = await provider.extract_entities(article.title, article.raw_content)

        # Region is entity-derived (country -> world region), so it works the
        # same regardless of which provider extracted the entities.
        region = detect_region(entities)
        subcategory = await provider.subcategorize(article.title, article.raw_content, category)
        if category == "events":
            # Events don't have keyword-detectable subcategories -- they're
            # "regional" whenever a region was detected, "general" otherwise.
            subcategory = "regional" if region else "general"

        headline = headline[:500] or article.title
        # Real Turkish translation only happens when a translation-capable LLM
        # is configured (see app/llm/base.py); the heuristic fallback always
        # returns None here, and both fields stay null -- surfaced honestly by
        # the API as is_translated=False rather than faked.
        headline_tr = await provider.translate(headline)
        summary_tr = await provider.translate(summary) if summary else None
        translated = headline_tr is not None and (summary_tr is not None or not summary)

        corroborating_count, confidence = await compute_confidence(db, article)

        enrichment = ArticleEnrichment(
            article_id=article.id,
            headline=headline,
            summary=summary,
            category=category,
            subcategory=subcategory,
            region=region,
            importance_score=_importance_score(confidence, corroborating_count),
            sentiment=sentiment,
            confidence_score=confidence,
            corroborating_source_count=corroborating_count,
            verified_at=datetime.now(timezone.utc),
            llm_provider_used=provider.name,
            tags=",".join(sorted({e.entity_type for e in entities})),
            headline_tr=headline_tr,
            summary_tr=summary_tr,
            translated_at=datetime.now(timezone.utc) if translated else None,
            translation_provider=provider.name if translated else None,
        )
        db.add(enrichment)
        await db.flush()

        for mention in entities:
            entity = await entity_repo.get_or_create(mention.entity_type, mention.name, mention.code)
            db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))

        await index_article_text(
            db, article.id, f"{article.title} {headline} {summary} {enrichment.tags}"
        )
        article.status = "enriched"

    await db.commit()
    logger.info("enrichment_run_complete", enriched=len(articles))
    return len(articles)


async def translate_pending_articles(db: AsyncSession, limit: int = 12) -> int:
    """Fill in Turkish translation for already-enriched articles that don't have
    it yet -- in place, without touching status, category, or anything else.

    The steady-state cron translates new articles as they're ingested, but a
    backlog enriched before a translator was configured (or by the heuristic,
    which can't translate) stays English. This backfills it a batch at a time,
    freshest first, so the site fills with Turkish over successive runs without
    ever un-publishing an article the way a full re-enrich would.

    Only rows with translated_at IS NULL are touched, which by construction
    excludes the curated events (they carry translation_provider='curated' and a
    translated_at) -- their hand-written Turkish is never overwritten.
    """
    provider = get_llm_provider()

    result = await db.execute(
        select(ArticleEnrichment)
        .join(Article, Article.id == ArticleEnrichment.article_id)
        .where(
            Article.is_duplicate.is_(False),
            Article.status == "enriched",
            ArticleEnrichment.translated_at.is_(None),
        )
        .order_by(Article.published_at.desc().nulls_last())
        .limit(limit)
    )
    enrichments = list(result.scalars().all())

    translated = 0
    for enrichment in enrichments:
        headline_tr = await provider.translate(enrichment.headline) if enrichment.headline else None
        summary_tr = await provider.translate(enrichment.summary) if enrichment.summary else None
        # translate() returns None when no real translator ran; only mark the row
        # translated when we actually got Turkish back, so is_translated stays honest.
        if headline_tr is None and summary_tr is None:
            continue
        enrichment.headline_tr = headline_tr
        enrichment.summary_tr = summary_tr
        enrichment.translated_at = datetime.now(timezone.utc)
        enrichment.translation_provider = provider.name
        translated += 1

    await db.commit()
    logger.info("translation_backfill_complete", translated=translated, considered=len(enrichments))
    return translated


async def reset_enrichment(db: AsyncSession, days: int | None = None) -> int:
    """Drop existing enrichment so the next run redoes it from scratch.

    Needed whenever the pipeline itself changes -- a new categorisation
    taxonomy, or an LLM becoming available where there was none -- because
    enrichment is only ever computed once per article, at ingest. Deletes the
    derived rows (enrichment + entity links) and rewinds status to "deduped";
    the raw article is never touched.
    """
    query = select(Article).where(Article.is_duplicate.is_(False))
    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(Article.fetched_at >= since)

    articles = list((await db.execute(query)).scalars().all())
    article_ids = [a.id for a in articles]
    if not article_ids:
        return 0

    await db.execute(delete(ArticleEntity).where(ArticleEntity.article_id.in_(article_ids)))
    await db.execute(
        delete(ArticleEnrichment).where(ArticleEnrichment.article_id.in_(article_ids))
    )
    for article in articles:
        article.status = "deduped"

    await db.commit()
    logger.info("enrichment_reset", articles=len(article_ids), days=days)
    return len(article_ids)
