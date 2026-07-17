import uuid
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article, ArticleEnrichment


class ArticleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def url_exists(self, url: str) -> bool:
        result = await self.db.execute(select(exists().where(Article.url == url)))
        return bool(result.scalar())

    async def create(self, article: Article) -> Article:
        self.db.add(article)
        await self.db.flush()
        return article

    @staticmethod
    def _apply_filters(
        query,
        *,
        category: str | None,
        subcategory: str | None,
        region: str | None,
        since: datetime | None,
    ):
        """Shared filter clause for list_recent and count, so the "load more"
        pagination in the newspaper can trust that total counts the same rows
        the list returns (rather than every article ever ingested)."""
        query = query.where(Article.is_duplicate.is_(False))
        if since is not None:
            query = query.where(Article.published_at >= since)
        if category or subcategory or region:
            query = query.join(ArticleEnrichment)
            if category:
                query = query.where(ArticleEnrichment.category == category)
            if subcategory:
                query = query.where(ArticleEnrichment.subcategory == subcategory)
            if region:
                query = query.where(ArticleEnrichment.region == region)
        return query

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        category: str | None = None,
        subcategory: str | None = None,
        region: str | None = None,
        since: datetime | None = None,
    ) -> list[Article]:
        query = (
            select(Article)
            .options(selectinload(Article.source), selectinload(Article.enrichment))
            .order_by(Article.published_at.desc().nulls_last(), Article.fetched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        query = self._apply_filters(
            query, category=category, subcategory=subcategory, region=region, since=since
        )
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def count(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        region: str | None = None,
        since: datetime | None = None,
    ) -> int:
        query = self._apply_filters(
            select(func.count(Article.id.distinct())).select_from(Article),
            category=category,
            subcategory=subcategory,
            region=region,
            since=since,
        )
        result = await self.db.execute(query)
        return int(result.scalar_one())

    async def count_by_category(self, since: datetime | None = None) -> dict[str, int]:
        """One grouped query behind the newspaper's tab badges -- the alternative
        is a request per category every time the page loads."""
        query = (
            select(ArticleEnrichment.category, func.count())
            .join(Article, Article.id == ArticleEnrichment.article_id)
            .where(Article.is_duplicate.is_(False))
            .group_by(ArticleEnrichment.category)
        )
        if since is not None:
            query = query.where(Article.published_at >= since)
        result = await self.db.execute(query)
        return {category: count for category, count in result.all()}

    async def get_by_id(self, article_id: uuid.UUID) -> Article | None:
        result = await self.db.execute(
            select(Article)
            .options(selectinload(Article.source), selectinload(Article.enrichment))
            .where(Article.id == article_id)
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 200) -> list[Article]:
        result = await self.db.execute(
            select(Article).where(Article.status == status).limit(limit)
        )
        return list(result.scalars().all())
