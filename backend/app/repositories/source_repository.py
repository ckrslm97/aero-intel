from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.base import FetchHealth
from app.ingest.sources_seed import ALL_SOURCES, SourceSeed
from app.models.source import Source


class SourceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self) -> list[Source]:
        result = await self.db.execute(select(Source).where(Source.is_active.is_(True)))
        return list(result.scalars().all())

    async def ensure_seeded(self) -> None:
        """Reconcile the `sources` table with the curated seed list.

        app/ingest/sources_seed.py is the source of truth for which sources
        exist and what their fields are. This runs on every ingestion pass and
        is safe to repeat.

        Three cases, and the last two are the reason this is a reconcile rather
        than an insert-if-missing:

        * **New name** -> inserted.
        * **Existing name** -> every field is written back. Previously a row was
          skipped once its name was present, so a corrected URL or a re-tiered
          trust weight never reached a database that had already been seeded --
          the edit looked applied in the diff and did nothing in production.
        * **Name no longer in the seed list** -> deactivated, not deleted
          (articles reference sources). Previously a source stayed active
          forever once seeded, so deleting a feed from this file did not stop
          it being fetched. Removing a source from the seed list is how a
          source gets retired, and it has to actually work.

        Membership is therefore owned by the file, not the database: a row that
        is in the seed list is set active. Flipping `is_active` by hand in the
        database is not a supported workflow -- it would be undone on the next
        ingestion run. Retire a source by removing it from the seed list.
        """
        result = await self.db.execute(select(Source))
        by_name = {source.name: source for source in result.scalars().all()}
        seeded_names = set()

        for seed in ALL_SOURCES:
            seeded_names.add(seed.name)
            existing = by_name.get(seed.name)
            if existing is None:
                self.db.add(_source_from_seed(seed))
                continue
            _apply_seed(existing, seed)

        for name, source in by_name.items():
            if name not in seeded_names and source.is_active:
                source.is_active = False

        await self.db.commit()

    @staticmethod
    def record_health(source: Source, health: FetchHealth) -> None:
        """Fold one run's outcome into a source's health columns.

        Static because it touches no session state -- it mutates an ORM
        instance the caller already holds, and the caller's unit of work is
        what persists it.

        Deliberately not a commit: `run_ingestion` already commits once at the
        end of the pass, and health is part of that same run, not a separate
        fact that should survive a failed article write.

        The asymmetry between the branches is the point. A success clears the
        failure counter but leaves `last_failure_at` and `last_http_status`
        standing, because "last time this broke, it was a 403" stays true and
        useful after a recovery -- an intermittently blocked feed is a
        different problem from a healthy one, and zeroing the history would
        hide the flapping. A failure leaves `last_success_at` and
        `last_article_count` standing for the same reason: the age of the last
        success is exactly what the silent-death check reads.
        """
        if health.ok:
            source.last_success_at = health.at
            source.consecutive_failures = 0
            source.last_article_count = health.article_count
            return
        source.last_failure_at = health.at
        source.last_http_status = health.http_status
        source.consecutive_failures = (source.consecutive_failures or 0) + 1


def _apply_seed(source: Source, seed: SourceSeed) -> None:
    source.url = seed.url
    source.source_type = seed.source_type
    source.category = seed.category
    source.trust_weight = seed.trust_weight
    source.tier = seed.tier
    source.language = seed.language
    source.is_premium_stub = seed.is_premium_stub
    source.is_active = True
    # Editorial config is seed-owned exactly like the fields above -- edit
    # sources_seed.py and the next reconcile carries it. Deliberately NOT
    # applied to the health columns below, which are run-owned: a reconcile
    # must never reset a failure counter.
    source.priority = seed.priority
    source.news_categories = seed.news_categories
    source.crawl_frequency_minutes = seed.crawl_frequency_minutes


def _source_from_seed(seed: SourceSeed) -> Source:
    return Source(
        name=seed.name,
        url=seed.url,
        source_type=seed.source_type,
        category=seed.category,
        trust_weight=seed.trust_weight,
        tier=seed.tier,
        language=seed.language,
        is_premium_stub=seed.is_premium_stub,
        priority=seed.priority,
        news_categories=seed.news_categories,
        crawl_frequency_minutes=seed.crawl_frequency_minutes,
        consecutive_failures=0,
    )
