from datetime import datetime, timezone

from app.models.article import Article
from app.models.source import Source
from app.pipeline.search_indexing import index_article_text
from app.search.postgres_fts import PostgresFtsBackend


async def test_search_finds_matching_article_and_excludes_duplicates(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    match = Article(
        source_id=source.id,
        url="https://example.com/match",
        title="Turkish Airlines expands Africa network",
        raw_content="Turkish Airlines announced new routes across Africa.",
        fetched_at=datetime.now(timezone.utc),
        content_hash="match",
        status="enriched",
    )
    unrelated = Article(
        source_id=source.id,
        url="https://example.com/unrelated",
        title="Fuel prices rise slightly",
        raw_content="Jet fuel prices ticked up this week.",
        fetched_at=datetime.now(timezone.utc),
        content_hash="unrelated",
        status="enriched",
    )
    duplicate_match = Article(
        source_id=source.id,
        url="https://example.com/duplicate",
        title="Turkish Airlines expands Africa network (wire copy)",
        raw_content="Turkish Airlines announced new routes across Africa.",
        fetched_at=datetime.now(timezone.utc),
        content_hash="duplicate",
        status="duplicate",
        is_duplicate=True,
    )
    db_session.add_all([match, unrelated, duplicate_match])
    await db_session.flush()

    for article in (match, unrelated, duplicate_match):
        await index_article_text(db_session, article.id, f"{article.title} {article.raw_content}")
    await db_session.commit()

    backend = PostgresFtsBackend(db_session)
    results = await backend.search("Turkish Airlines Africa")

    result_urls = {a.url for a in results}
    assert match.url in result_urls
    assert unrelated.url not in result_urls
    assert duplicate_match.url not in result_urls
