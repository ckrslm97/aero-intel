from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _apply_seed(source: Source, seed: SourceSeed) -> None:
    source.url = seed.url
    source.source_type = seed.source_type
    source.category = seed.category
    source.trust_weight = seed.trust_weight
    source.is_premium_stub = seed.is_premium_stub
    source.is_active = True


def _source_from_seed(seed: SourceSeed) -> Source:
    return Source(
        name=seed.name,
        url=seed.url,
        source_type=seed.source_type,
        category=seed.category,
        trust_weight=seed.trust_weight,
        is_premium_stub=seed.is_premium_stub,
    )
