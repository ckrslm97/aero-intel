from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi import KPI


class KpiRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def record(
        self,
        metric_key: str,
        value: float,
        unit: str,
        source: str,
        is_estimate: bool,
        as_of: datetime,
        source_url: str | None = None,
        is_primary: bool = True,
    ) -> KPI:
        kpi = KPI(
            metric_key=metric_key,
            value=value,
            unit=unit,
            source=source,
            source_url=source_url,
            is_estimate=is_estimate,
            is_primary=is_primary,
            as_of=as_of,
        )
        self.db.add(kpi)
        return kpi

    async def latest(self, metric_key: str, is_primary: bool = True) -> KPI | None:
        """The newest observation, used to decide whether a new reading actually
        says anything different -- see kpi_service.record_if_changed()."""
        result = await self.db.execute(
            select(KPI)
            .where(KPI.metric_key == metric_key, KPI.is_primary.is_(is_primary))
            .order_by(KPI.as_of.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def exists_at(self, metric_key: str, as_of: datetime) -> bool:
        """Whether this exact observation is already stored -- lets the
        historical seed re-run without duplicating points."""
        result = await self.db.execute(
            select(KPI.id).where(KPI.metric_key == metric_key, KPI.as_of == as_of).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def trend(self, metric_key: str, points: int = 12) -> list[KPI]:
        """Most recent `points` primary observations, oldest first (sparkline order)."""
        result = await self.db.execute(
            select(KPI)
            .where(KPI.metric_key == metric_key, KPI.is_primary.is_(True))
            .order_by(KPI.as_of.desc())
            .limit(points)
        )
        return list(reversed(result.scalars().all()))

    async def history_since(self, metric_key: str, since: datetime) -> list[KPI]:
        """Our own accumulated primary observations since `since`, oldest first --
        used for metrics with no external historical source to fall back on."""
        result = await self.db.execute(
            select(KPI)
            .where(
                KPI.metric_key == metric_key,
                KPI.is_primary.is_(True),
                KPI.as_of >= since,
            )
            .order_by(KPI.as_of.asc())
        )
        return list(result.scalars().all())

    async def latest_corroborations(self, metric_key: str) -> list[KPI]:
        """Most recent secondary-source readings for this metric (one per
        distinct source), used to show 'confirmed against X' on the detail page."""
        result = await self.db.execute(
            select(KPI)
            .where(KPI.metric_key == metric_key, KPI.is_primary.is_(False))
            .order_by(KPI.as_of.desc())
            .limit(5)
        )
        seen_sources: set[str] = set()
        corroborations: list[KPI] = []
        for kpi in result.scalars().all():
            if kpi.source in seen_sources:
                continue
            seen_sources.add(kpi.source)
            corroborations.append(kpi)
        return corroborations

    async def distinct_metric_keys(self) -> list[str]:
        result = await self.db.execute(select(KPI.metric_key).distinct())
        return [row[0] for row in result.all()]
