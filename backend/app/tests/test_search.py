from datetime import datetime, timezone

from app.ingest.blacklist import BLACKLIST_STATUS
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


async def test_search_hides_blacklisted_sources_the_rest_of_the_app_hides(db_session):
    """Search was the one listing that never applied the blacklist.

    Every other surface filters on `status != BLACKLIST_STATUS` through
    `_NOT_BLACKLISTED` in app/repositories/article_repository.py, so a retired
    domain vanishes from the Gazete, the archive and every facet count -- and
    remained reachable by typing its headline into the search box, complete
    with its row counted in the "N sonuç" total. Two surfaces, one corpus, two
    answers.

    Asserted from both sides: the blacklisted row disappears from the results
    AND from the count, while an ordinary row on the same query does not.
    """
    source = Source(name="Retired Source", url="https://reddit.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    kept = Article(
        source_id=source.id,
        url="https://example.com/kept",
        title="Lufthansa cargo capacity climbs",
        raw_content="Lufthansa reported higher cargo capacity this quarter.",
        fetched_at=datetime.now(timezone.utc),
        content_hash="kept-cargo",
        status="enriched",
    )
    retired = Article(
        source_id=source.id,
        url="https://reddit.com/r/aviation/lufthansa",
        title="Lufthansa cargo capacity climbs (thread)",
        raw_content="Lufthansa reported higher cargo capacity this quarter.",
        fetched_at=datetime.now(timezone.utc),
        content_hash="retired-cargo",
        status=BLACKLIST_STATUS,
    )
    db_session.add_all([kept, retired])
    await db_session.flush()

    for article in (kept, retired):
        await index_article_text(db_session, article.id, f"{article.title} {article.raw_content}")
    await db_session.commit()

    backend = PostgresFtsBackend(db_session)
    results = await backend.search("Lufthansa cargo capacity")

    result_urls = {a.url for a in results}
    assert kept.url in result_urls
    assert retired.url not in result_urls
    # The count reads the same builder, so the total cannot describe a larger
    # set than the page under it.
    assert await backend.count("Lufthansa cargo capacity") == 1
