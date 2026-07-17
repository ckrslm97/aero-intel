from datetime import datetime, timedelta, timezone

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
    # Egypt is mentioned in the article body -> region should be entity-derived.
    assert enrichment.region == "africa"
    # No LLM is configured in tests -> the heuristic engine cannot translate,
    # and this must be surfaced honestly rather than faked.
    assert enrichment.headline_tr is None
    assert enrichment.summary_tr is None
    assert enrichment.translated_at is None

    links = await db_session.execute(
        select(ArticleEntity).where(ArticleEntity.article_id == article.id)
    )
    assert len(links.scalars().all()) > 0


async def test_enrich_events_article_gets_regional_subcategory(db_session):
    source = Source(
        name="Test Source 2", url="https://example.com/feed2", source_type="rss", trust_weight=0.8
    )
    db_session.add(source)
    await db_session.flush()

    article = Article(
        source_id=source.id,
        url="https://example.com/events-1",
        title="Airline executives to attend aviation summit in Turkey",
        raw_content=(
            "Industry leaders will gather for the aviation conference and expo in Turkey "
            "next month to discuss the year ahead."
        ),
        fetched_at=datetime.now(timezone.utc),
        content_hash="hash-events-1",
        status="deduped",
    )
    db_session.add(article)
    await db_session.flush()

    await enrich_pending_articles(db_session)

    result = await db_session.execute(
        select(ArticleEnrichment).where(ArticleEnrichment.article_id == article.id)
    )
    enrichment = result.scalar_one()
    assert enrichment.category == "events"
    # A region (Turkey -> middle-east) was detected, so the events article is
    # bucketed "regional" rather than "general" -- see app/pipeline/enrich.py.
    assert enrichment.region == "middle-east"
    assert enrichment.subcategory == "regional"


async def test_batch_limit_enriches_only_the_freshest_articles(db_session):
    source = Source(name="S", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    # Three deduped articles, oldest to newest by published_at.
    for i, offset in enumerate([0, 1, 2]):
        db_session.add(
            Article(
                source_id=source.id,
                url=f"https://example.com/a{i}",
                title=f"Airline news {i}",
                raw_content="An airline announced something noteworthy this quarter.",
                published_at=base + timedelta(days=offset),
                fetched_at=datetime.now(timezone.utc),
                content_hash=f"hash-{i}",
                status="deduped",
            )
        )
    await db_session.flush()

    # Budget only allows two this run.
    enriched = await enrich_pending_articles(db_session, limit=2)
    assert enriched == 2

    enriched_titles = {
        row.title
        for row in (
            await db_session.execute(
                select(Article).where(Article.status == "enriched")
            )
        ).scalars()
    }
    # The two most recently published were taken; the oldest waits for next run.
    assert enriched_titles == {"Airline news 2", "Airline news 1"}

    still_pending = (
        await db_session.execute(select(Article).where(Article.status == "deduped"))
    ).scalars().all()
    assert [a.title for a in still_pending] == ["Airline news 0"]
