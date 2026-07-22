"""Postgres full-text search over the GIN-indexed Article.search_vector column."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.repositories.article_repository import article_out_loaders


class PostgresFtsBackend:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(self, query: str, limit: int = 20) -> list[Article]:
        tsquery = func.plainto_tsquery("english", query)
        rank = func.ts_rank(Article.search_vector, tsquery)

        result = await self.db.execute(
            select(Article)
            .options(*article_out_loaders())
            .where(Article.search_vector.op("@@")(tsquery), Article.is_duplicate.is_(False))
            .order_by(rank.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())
