"""Postgres full-text search over the GIN-indexed Article.search_vector column."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article, ArticleEnrichment
from app.repositories.article_repository import article_out_loaders


class PostgresFtsBackend:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base(self, query: str, category: str | None, days: int | None):
        """The WHERE clause both the page and the count read.

        One builder rather than two, for the reason /articles has one: a total
        computed on a different predicate than the list is a number that lies
        about the list underneath it.
        """
        tsquery = func.plainto_tsquery("english", query)
        clause = select(Article).where(
            Article.search_vector.op("@@")(tsquery), Article.is_duplicate.is_(False)
        )
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            clause = clause.where(
                func.coalesce(Article.published_at, Article.fetched_at) >= since
            )
        if category:
            clause = clause.join(ArticleEnrichment).where(
                ArticleEnrichment.category == category
            )
        return clause, tsquery

    async def search(
        self,
        query: str,
        limit: int = 20,
        category: str | None = None,
        days: int | None = None,
    ) -> list[Article]:
        clause, tsquery = self._base(query, category, days)
        result = await self.db.execute(
            clause.options(*article_out_loaders())
            .order_by(func.ts_rank(Article.search_vector, tsquery).desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def count(
        self, query: str, category: str | None = None, days: int | None = None
    ) -> int:
        """How many articles the query actually matches.

        /search used to report `len(results)` as its total, so a query with
        four hundred matches said "20 sonuç" -- the page size, presented as the
        size of the corpus. This is one extra count query per search, which is
        an entirely reasonable price for a number that is true.
        """
        clause, _ = self._base(query, category, days)
        result = await self.db.execute(
            select(func.count()).select_from(clause.subquery())
        )
        return int(result.scalar_one())
