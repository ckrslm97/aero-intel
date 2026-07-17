"""Tab badges need one grouped query, not one request per category."""
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.repositories.article_repository import ArticleRepository

NOW = datetime.now(timezone.utc)


async def _article(db_session, source, *, category, published_at, is_duplicate=False):
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{category}-{published_at.isoformat()}-{is_duplicate}",
        title="t",
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=f"{category}-{published_at.isoformat()}-{is_duplicate}",
        status="enriched",
        is_duplicate=is_duplicate,
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(ArticleEnrichment(article_id=article.id, category=category))
    await db_session.flush()


async def test_counts_group_by_category(db_session):
    source = Source(name="S", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    await _article(db_session, source, category="events", published_at=NOW)
    await _article(db_session, source, category="events", published_at=NOW - timedelta(hours=1))
    await _article(db_session, source, category="fleet", published_at=NOW)
    await db_session.commit()

    counts = await ArticleRepository(db_session).count_by_category()

    assert counts == {"events": 2, "fleet": 1}


async def test_counts_respect_the_recency_window(db_session):
    source = Source(name="S2", url="https://example.com/feed2", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    await _article(db_session, source, category="fleet", published_at=NOW)
    await _article(db_session, source, category="fleet", published_at=NOW - timedelta(days=40))
    await db_session.commit()

    counts = await ArticleRepository(db_session).count_by_category(since=NOW - timedelta(days=30))

    assert counts == {"fleet": 1}


async def test_counts_exclude_duplicates(db_session):
    source = Source(name="S3", url="https://example.com/feed3", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    await _article(db_session, source, category="safety", published_at=NOW)
    # A wire-copy duplicate must not inflate the badge.
    await _article(db_session, source, category="safety", published_at=NOW, is_duplicate=True)
    await db_session.commit()

    counts = await ArticleRepository(db_session).count_by_category()

    assert counts == {"safety": 1}
