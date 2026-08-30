import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.taxonomy import DEFAULT_UNDECLARED_TIER, FOCUS_BONUS, RIVAL_CODES, TRUST_WEIGHT_TIERS

# Articles are timestamped in UTC but published_at can be missing for feeds
# that omit dates -- day-based views (the archive) fall back to fetched_at so
# every article belongs to exactly one day.
_DAY_EXPR = func.coalesce(Article.published_at, Article.fetched_at)


def _focus_weighted_importance():
    """`importance_score + FOCUS_BONUS[category]`, as SQL.

    The Gazete's `min_importance` floor compares against this, not against the
    raw column. importance_score is `confidence * 0.7 + min(corroborating, 5) *
    0.06`, which rewards *corroboration* -- so a flat floor on it keeps the
    stories ten wires ran and drops the ones a single outlet broke. Measured
    over 30 days, a flat 0.47 kept 52% of Filo but only 15% of Gelir Yönetimi
    and 35% of Etkinlik: exactly backwards from the desk's priority, because a
    Boeing order is on every wire while a rival's fare move is on one.

    Adding the same editorial bonus the front page already ranks by
    (app/services/edition_service.py) makes the floor mean "important to an RM
    desk" instead of "widely syndicated". Ordering follows the desk's priority
    once weighted: Gelir Yönetimi and Etkinlik keep a larger share than Filo
    and Genel, which is the point.

    NULL-safe on both sides: importance_score is nullable, and a category with
    no bonus (or a NULL category) falls through the CASE to 0.0.
    """
    bonus = case(FOCUS_BONUS, value=ArticleEnrichment.category, else_=0.0)
    return func.coalesce(ArticleEnrichment.importance_score, 0.0) + bonus


def _sources_in_tiers(tiers: list[str]):
    """Source ids whose EFFECTIVE tier is one of `tiers`.

    The same ladder app.taxonomy.effective_source_tier walks in Python, written
    once as SQL from the same table -- a hand-typed CASE here would be a second
    copy of the thresholds, and the two would disagree the first time one was
    tuned. `Source.tier` is nullable, so the trust_weight buckets are not an
    edge case: they are what every source seeded before that column existed
    still resolves through.

    A semi-join rather than a join, for the reason the airline filter is one:
    the source list is short (tens of rows), and IN (subquery) cannot multiply
    an article across the LIMIT the way a join can.
    """
    ladder = case(
        *[(Source.trust_weight >= floor, name) for floor, name in TRUST_WEIGHT_TIERS],
        else_=DEFAULT_UNDECLARED_TIER,
    )
    effective = case((Source.tier.isnot(None), Source.tier), else_=ladder)
    return select(Source.id).where(effective.in_(tiers))


def _entity_mentions(entity_type: str, value: str, *, by_code: bool = True):
    """Article ids that mention one named entity.

    A semi-join for the same reason the airline filter is one: an article that
    names a country three times must still count once, or LIMIT pages over
    duplicate rows.
    """
    column = Entity.code if by_code else Entity.name
    return (
        select(ArticleEntity.article_id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(Entity.entity_type == entity_type, func.lower(column) == value.lower())
    )


def article_out_loaders():
    """Everything ArticleOut touches, eager-loaded.

    ArticleOut derives `airlines` and `airports` from the entity links, so any
    query whose rows get serialised has to load them here. Miss one and it
    fails only in production: the tests keep objects in the session's identity
    map, where a lazy load quietly succeeds, while a real request has already
    left the greenlet by the time Pydantic reads the attribute.
    """
    return (
        selectinload(Article.source),
        selectinload(Article.enrichment),
        selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
    )


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
        country: str | None = None,
        airport: str | None = None,
        translated_only: bool = False,
        exclude_categories: list[str] | None = None,
        min_importance: float | None = None,
        tiers: list[str] | None = None,
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
        if (
            category
            or subcategory
            or region
            or translated_only
            or exclude_categories
            or min_importance is not None
        ):
            # One join covers every enrichment-backed filter; the condition
            # mirrors the clauses below so translated_only can pull the join in
            # on its own without double-joining when a category already did.
            query = query.join(ArticleEnrichment)
            if category:
                query = query.where(ArticleEnrichment.category == category)
            if subcategory:
                query = query.where(ArticleEnrichment.subcategory == subcategory)
            if region:
                query = query.where(ArticleEnrichment.region == region)
            if translated_only:
                # translated_at is only stamped when the LLM actually produced
                # Turkish text -- articles that never got translated (or whose
                # translation failed) fall back to their original-language
                # headline, which has no business in a Turkish paper.
                query = query.where(ArticleEnrichment.translated_at.isnot(None))
            if exclude_categories:
                # The Gazete's simplification: four categories are still
                # ingested and classified (nothing is deleted), they are just
                # not part of the paper. Opt-in per request, so the archive,
                # search, the hubs and the per-date edition keep full coverage.
                query = query.where(
                    ArticleEnrichment.category.notin_(exclude_categories)
                )
            if min_importance is not None:
                # "Fewer, more critical stories" -- but weighted, see
                # _focus_weighted_importance(): a flat floor on the raw column
                # is a floor on how widely syndicated a story is, which culls
                # the desk's two priority beats hardest.
                query = query.where(_focus_weighted_importance() >= min_importance)
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
        # Country and airport read the same entity table. Region already exists
        # as a filter, but a region is nine countries wide: a network planner
        # asking "what is happening in Japan" does not want all of Asia, and a
        # hub page is about one airport, not the continent it sits on.
        if country:
            query = query.where(Article.id.in_(_entity_mentions("country", country, by_code=False)))
        if airport:
            query = query.where(Article.id.in_(_entity_mentions("airport", airport)))
        if tiers:
            # Source authority as a filter -- "official and regulator only" is a
            # different reading of the same day than "everything the wires ran".
            # Server-side rather than a pass over the loaded page, because the
            # list is paginated: filtering 30 rows client-side would leave page
            # 2 holding stories page 1's filter should have shown.
            query = query.where(Article.source_id.in_(_sources_in_tiers(tiers)))
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
        country: str | None = None,
        airport: str | None = None,
        translated_only: bool = False,
        exclude_categories: list[str] | None = None,
        min_importance: float | None = None,
        tiers: list[str] | None = None,
    ) -> list[Article]:
        query = (
            select(Article)
            .options(
                *article_out_loaders(),
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
            country=country,
            airport=airport,
            translated_only=translated_only,
            exclude_categories=exclude_categories,
            min_importance=min_importance,
            tiers=tiers,
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
        country: str | None = None,
        airport: str | None = None,
        translated_only: bool = False,
        exclude_categories: list[str] | None = None,
        min_importance: float | None = None,
        tiers: list[str] | None = None,
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
            country=country,
            airport=airport,
            translated_only=translated_only,
            exclude_categories=exclude_categories,
            min_importance=min_importance,
            tiers=tiers,
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

    async def count_by_category(
        self,
        since: datetime | None = None,
        translated_only: bool = False,
        exclude_categories: list[str] | None = None,
        min_importance: float | None = None,
    ) -> dict[str, int]:
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
        # Same clause the list uses, so a badge counts exactly the rows the
        # filtered list will render (this query already joins the enrichment).
        if translated_only:
            query = query.where(ArticleEnrichment.translated_at.isnot(None))
        if exclude_categories:
            query = query.where(ArticleEnrichment.category.notin_(exclude_categories))
        if min_importance is not None:
            # Identical predicate to _apply_filters, focus weighting included --
            # a badge counting rows on a different rule than the list is a badge
            # that lies, and the weighting shifts counts a long way per category.
            query = query.where(_focus_weighted_importance() >= min_importance)
        result = await self.db.execute(query)
        return {category: count for category, count in result.all()}

    async def get_by_id(self, article_id: uuid.UUID) -> Article | None:
        result = await self.db.execute(
            select(Article)
            .options(*article_out_loaders())
            .where(Article.id == article_id)
        )
        return result.scalar_one_or_none()

    async def list_duplicate_group(self, article_id: uuid.UUID) -> list[Article]:
        """The canonical article and every duplicate filed under it, oldest
        publication first.

        Exactly the set app/pipeline/verify.py counts to produce
        `corroborating_source_count` -- deliberately the same `id == x OR
        duplicate_of_id == x` predicate, so the list a reader opens can never
        disagree with the number the drawer printed. One indexed lookup plus
        the FK index on duplicate_of_id; no aggregation, no second pass.

        Ordered by publication so the result reads as a chronology: who ran it
        first, who followed. Undated rows sort last rather than being dropped.
        """
        result = await self.db.execute(
            select(Article)
            .options(selectinload(Article.source), defer(Article.raw_content))
            .where((Article.id == article_id) | (Article.duplicate_of_id == article_id))
            .order_by(Article.published_at.asc().nulls_last(), Article.fetched_at.asc())
        )
        return list(result.scalars().unique().all())

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
