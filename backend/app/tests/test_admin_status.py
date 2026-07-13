from datetime import datetime, timezone

from app.api.v1.admin import admin_status
from app.models.article import Article
from app.models.source import Source
from app.models.subscriber import Subscriber


async def test_admin_status_aggregates_real_counts(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    db_session.add_all(
        [
            Article(
                source_id=source.id,
                url="https://example.com/a",
                title="A",
                fetched_at=datetime.now(timezone.utc),
                content_hash="a",
                status="enriched",
            ),
            Article(
                source_id=source.id,
                url="https://example.com/b",
                title="B",
                fetched_at=datetime.now(timezone.utc),
                content_hash="b",
                status="new",
            ),
        ]
    )
    db_session.add(Subscriber(email="reader@example.com"))
    await db_session.commit()

    status = await admin_status(db_session)

    assert status.sources_count == 1
    assert status.subscribers_count == 1
    counts_by_status = {s.status: s.count for s in status.articles_by_status}
    assert counts_by_status == {"enriched": 1, "new": 1}
    assert status.latest_article_fetched_at is not None
    assert isinstance(status.scheduler_jobs, list)
