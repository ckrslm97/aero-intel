import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.taxonomy import RIVAL_CODES

# Articles are timestamped in UTC but published_at can be missing for feeds
# that omit dates -- day-based views (the archive) fall back to fetched_at so
# every article belongs to exactly one day.
_DAY_EXPR = func.coalesce(Article.published_at, Article.fetched_at)


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
        airline: str | None = None,
        on_date: date | None = None,
    ):
        """Shared filter clause for list_recent and count, so the "load more"
        pagination in the newspaper can trust that total counts the same rows
        the list returns (rather than every article ever ingested)."""
        query = query.where(Article.is_duplicate.is_(False))
        if since is not None:
            query = query.where(Article.published_at >= since)
        if on_date is not None:
            day_start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
            query = query.where(
                _DAY_EXPR >= day_start, _DAY_EXPR < day_start + timedelta(days=1)
            )
        if category or subcategory or region:
            query = query.join(ArticleEnrichment)
            if category:
                query = query.where(ArticleEnrichment.category == category)
            if subcategory:
                query = query.where(ArticleEnrichment.subcategory == subcategory)
            if region:
                query = query.where(ArticleEnrichment.region == region)
        if airline:
            # Entity-based: the "Ana Rakipler" filter matches any article that
            # *mentions* the airline, regardless of category -- rival news lives
            # in fleet/network/finance as much as in revenue_management.
            # Two special values: RIVALS = any of the user's named main rivals,
            # ALL = any airline entity at all ("Tüm Taşıyıcılar").
            #
            # A semi-join, NOT a join: joining multiplied rows for articles that
            # mention several airlines, and since LIMIT/OFFSET apply to the
            # joined rows, "?airline=ALL&limit=30" returned 21 articles and
            # paging skipped stories. IN (subquery) matches each article once.
            mentions = (
                select(ArticleEntity.article_id)
                .join(Entity, Entity.id == ArticleEntity.entity_id)
                .where(Entity.entity_type == "airline")
            )
            if airline == "RIVALS":
                mentions = mentions.where(Entity.code.in_(RIVAL_CODES))
            elif airline != "ALL":
                mentions = mentions.where(Entity.code == airline)
            query = query.where(Article.id.in_(mentions))
        return query

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        category: str | None = None,
        subcategory: str | None = None,
        region: str | None = None,
        since: datetime | None = None,
        airline: str | None = None,
        on_date: date | None = None,
    ) -> list[Article]:
        query = (
            select(Article)
            .options(
                selectinload(Article.source),
                selectinload(Article.enrichment),
                # The scraped body is never rendered in a list and is not part
                # of the JSON; leaving it in the SELECT moved hundreds of KB per
                # request out of Postgres for nothing (reading time now comes
                # from the stored word_count).
                defer(Article.raw_content),
            )
            .order_by(Article.published_at.desc().nulls_last(), Article.fetched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        query = self._apply_filters(
            query,
            category=category,
            subcategory=subcategory,
            region=region,
            since=since,
            airline=airline,
            on_date=on_date,
        )
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def count(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        region: str | None = None,
        since: datetime | None = None,
        airline: str | None = None,
        on_date: date | None = None,
    ) -> int:
        # Plain COUNT, not COUNT(DISTINCT): the airline filter is a semi-join
        # now, so no clause can multiply rows, and COUNT(DISTINCT uuid) forces
        # an extra sort/hash over the whole filtered set.
        query = self._apply_filters(
            select(func.count(Article.id)).select_from(Article),
            category=category,
            subcategory=subcategory,
            region=region,
            since=since,
            airline=airline,
            on_date=on_date,
        )
        result = await self.db.execute(query)
        return int(result.scalar_one())

    async def count_by_day(self, days: int = 7) -> dict[str, int]:
        """Article count per UTC day over the last `days` days -- the archive
        page's date-strip badges. Keys are ISO dates; days with no articles are
        simply absent (the frontend fills zeros)."""
        cutoff = datetime.combine(
            datetime.now(timezone.utc).date() - timedelta(days=days - 1),
            time.min,
            tzinfo=timezone.utc,
        )
        # timezone('UTC', ...) first: date_trunc on a bare timestamptz truncates
        # in the *session* timezone, which shifts every late-evening UTC article
        # into the wrong day on any non-UTC deployment (bitten by this before).
        day_col = func.date_trunc("day", func.timezone("UTC", _DAY_EXPR))
        query = (
            select(day_col, func.count())
            .where(Article.is_duplicate.is_(False), _DAY_EXPR >= cutoff)
            .group_by(day_col)
        )
        result = await self.db.execute(query)
        return {day.date().isoformat(): count for day, count in result.all()}

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
            select(Article)
            # The enrichment pipeline reads article.source.name to strip the
            # aggregator's " - Publisher" suffix. Without this eager load that
            # attribute access is a lazy SELECT, which under asyncio raises
            # MissingGreenlet and killed every scheduled ingest run for a day.
            .options(selectinload(Article.source))
            .where(Article.status == status)
            .limit(limit)
        )
        return list(result.scalars().all())
