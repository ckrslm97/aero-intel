from datetime import datetime, timezone

from sqlalchemy import select

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.models.source import Source
from app.pipeline.enrich import enrich_pending_articles


async def test_enrich_pending_articles_creates_enrichment_and_entities(db_session):
    source = Source(
        name="Test Source", url="https://example.com/feed", source_type="rss", trust_weight=0.8
    )
    db_session.add(source)
    await db_session.flush()

    article = Article(
        source_id=source.id,
        url="https://example.com/a",
        title="Turkish Airlines expands to Egypt",
        raw_content=(
            "Turkish Airlines announced a new route connecting Istanbul with Egypt. "
            "The airline said the new service will begin next quarter."
        ),
        fetched_at=datetime.now(timezone.utc),
        content_hash="hash-a",
        status="deduped",
    )
    db_session.add(article)
    await db_session.flush()

    enriched_count = await enrich_pending_articles(db_session)
    assert enriched_count == 1

    await db_session.refresh(article)
    assert article.status == "enriched"

    result = await db_session.execute(
        select(ArticleEnrichment).where(ArticleEnrichment.article_id == article.id)
    )
    enrichment = result.scalar_one()
    assert enrichment.headline
    assert enrichment.category
    assert enrichment.llm_provider_used == "heuristic"
    assert enrichment.corroborating_source_count == 1
    assert 0.0 <= enrichment.confidence_score <= 1.0

    links = await db_session.execute(
        select(ArticleEntity).where(ArticleEntity.article_id == article.id)
    )
    assert len(links.scalars().all()) > 0
