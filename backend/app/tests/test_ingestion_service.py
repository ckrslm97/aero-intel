from datetime import datetime, timezone

from sqlalchemy import select

from app.ingest.base import RawArticle
from app.models.article import Article
from app.models.source import Source
from app.services import ingestion_service


class FakeAdapter:
    def __init__(self, articles: list[RawArticle]):
        self.source_name = "Fake Source"
        self._articles = articles

    async def fetch(self) -> list[RawArticle]:
        return self._articles


async def test_run_ingestion_persists_new_articles(db_session, monkeypatch):
    source = Source(name="Fake Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    articles = [
        RawArticle(
            url="https://example.com/a",
            title="Delta announces new route",
            content="Delta Air Lines announced a new route today.",
            author="Jane Doe",
            published_at=datetime.now(timezone.utc),
        ),
        RawArticle(
            url="https://example.com/b",
            title="United fleet update",
            content="United Airlines updated its fleet plans.",
            author=None,
            published_at=None,
        ),
    ]

    monkeypatch.setattr(
        ingestion_service, "_adapter_for", lambda src: FakeAdapter(articles)
    )

    inserted = await ingestion_service.run_ingestion(db_session)

    assert inserted == 2
    result = await db_session.execute(select(Article))
    stored = result.scalars().all()
    assert {a.url for a in stored} == {"https://example.com/a", "https://example.com/b"}
    assert all(a.status == "new" for a in stored)


async def test_run_ingestion_skips_already_seen_urls(db_session, monkeypatch):
    source = Source(name="Fake Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    articles = [
        RawArticle(
            url="https://example.com/a",
            title="Delta announces new route",
            content="Delta Air Lines announced a new route today.",
            author=None,
            published_at=None,
        )
    ]
    monkeypatch.setattr(
        ingestion_service, "_adapter_for", lambda src: FakeAdapter(articles)
    )

    first = await ingestion_service.run_ingestion(db_session)
    second = await ingestion_service.run_ingestion(db_session)

    assert first == 1
    assert second == 0
