"""AI enrichment: headline, summary, category, sentiment, entities, and
cross-source confidence for every deduped (canonical) article.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.factory import get_llm_provider
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


async def enrich_pending_articles(db: AsyncSession) -> int:
    provider = get_llm_provider()
    entity_repo = EntityRepository(db)

    result = await db.execute(select(Article).where(Article.status == "deduped"))
    articles = list(result.scalars().all())

    for article in articles:
        headline = await provider.generate_headline(article.title, article.raw_content)
        summary = await provider.generate_summary(article.title, article.raw_content)
        category = await provider.categorize(article.title, article.raw_content)
        sentiment = await provider.sentiment(article.title, article.raw_content)
        entities = await provider.extract_entities(article.title, article.raw_content)

        corroborating_count, confidence = await compute_confidence(db, article)

        enrichment = ArticleEnrichment(
            article_id=article.id,
            headline=headline[:500] or article.title,
            summary=summary,
            category=category,
            importance_score=_importance_score(confidence, corroborating_count),
            sentiment=sentiment,
            confidence_score=confidence,
            corroborating_source_count=corroborating_count,
            verified_at=datetime.now(timezone.utc),
            llm_provider_used=provider.name,
            tags=",".join(sorted({e.entity_type for e in entities})),
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
