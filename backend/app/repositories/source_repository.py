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
        """Idempotently upsert the curated source list. Safe to call on every ingestion run."""
        result = await self.db.execute(select(Source.name))
        existing_names = {row[0] for row in result.all()}

        for seed in ALL_SOURCES:
            if seed.name in existing_names:
                continue
            self.db.add(_source_from_seed(seed))
        await self.db.commit()


def _source_from_seed(seed: SourceSeed) -> Source:
    return Source(
        name=seed.name,
        url=seed.url,
        source_type=seed.source_type,
        category=seed.category,
        trust_weight=seed.trust_weight,
        is_premium_stub=seed.is_premium_stub,
    )
