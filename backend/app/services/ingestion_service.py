"""Orchestrates one ingestion run: seed sources -> fetch every active source
concurrently -> persist new articles. Each adapter isolates its own failures,
so one broken feed never blocks the others.
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.base import RawArticle, SourceAdapter
from app.ingest.premium.registry import PREMIUM_ADAPTERS
from app.ingest.rss import RssSourceAdapter
from app.models.article import Article
from app.models.source import Source
from app.pipeline.hashing import content_hash
from app.pipeline.search_indexing import index_article_text
from app.repositories.article_repository import ArticleRepository
from app.repositories.source_repository import SourceRepository

logger = get_logger(__name__)


def _adapter_for(source: Source) -> SourceAdapter | None:
    if source.source_type == "rss":
        return RssSourceAdapter(source.name, source.url)
    if source.source_type == "premium":
        return next((a for a in PREMIUM_ADAPTERS if a.source_name == source.name), None)
    logger.warning("no_adapter_for_source_type", source=source.name, source_type=source.source_type)
    return None


async def _fetch_source(source: Source) -> tuple[Source, list[RawArticle]]:
    adapter = _adapter_for(source)
    if adapter is None:
        return source, []
    try:
        return source, await adapter.fetch()
    except Exception:  # noqa: BLE001 -- a single misbehaving adapter must not abort the run
        logger.exception("adapter_fetch_crashed", source=source.name)
        return source, []


async def run_ingestion(db: AsyncSession) -> int:
    source_repo = SourceRepository(db)
    article_repo = ArticleRepository(db)

    await source_repo.ensure_seeded()
    sources = await source_repo.list_active()

    results = await asyncio.gather(*(_fetch_source(source) for source in sources))

    inserted = 0
    for source, raw_articles in results:
        for raw in raw_articles:
            if await article_repo.url_exists(raw.url):
                continue
            article = Article(
                source_id=source.id,
                url=raw.url,
                title=raw.title[:500],
                raw_content=raw.content,
                author=raw.author[:200] if raw.author else None,
                published_at=raw.published_at,
                fetched_at=datetime.now(timezone.utc),
                content_hash=content_hash(raw.title, raw.content),
                status="new",
            )
            await article_repo.create(article)
            await index_article_text(db, article.id, f"{raw.title} {raw.content}")
            inserted += 1

    await db.commit()
    logger.info("ingestion_run_complete", sources=len(sources), inserted=inserted)
    return inserted
