from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.edition import Edition, EditionArticle
from app.repositories.article_repository import article_out_loaders


class EditionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_date(self, edition_date: date) -> Edition | None:
        result = await self.db.execute(
            select(Edition)
            .options(
                # Same set the API serialises elsewhere -- the edition endpoint
                # returns ArticleOut too, so it needs the entity links as well.
                *(
                    selectinload(Edition.articles)
                    .selectinload(EditionArticle.article)
                    .options(loader)
                    for loader in article_out_loaders()
                ),
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
