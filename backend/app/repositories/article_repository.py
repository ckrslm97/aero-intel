import uuid

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

    async def list_recent(
        self, limit: int = 50, offset: int = 0, category: str | None = None
    ) -> list[Article]:
        query = (
            select(Article)
            .options(selectinload(Article.source), selectinload(Article.enrichment))
            .where(Article.is_duplicate.is_(False))
            .order_by(Article.published_at.desc().nulls_last(), Article.fetched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if category:
            query = query.join(ArticleEnrichment).where(ArticleEnrichment.category == category)
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Article))
        return int(result.scalar_one())

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
