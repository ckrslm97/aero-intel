from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article
from app.models.edition import Edition, EditionArticle


class EditionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_date(self, edition_date: date) -> Edition | None:
        result = await self.db.execute(
            select(Edition)
            .options(
                selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.source),
                selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.enrichment),
            )
            .where(Edition.edition_date == edition_date)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 30) -> list[Edition]:
        result = await self.db.execute(
            select(Edition)
            .options(selectinload(Edition.articles))
            .order_by(Edition.edition_date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
