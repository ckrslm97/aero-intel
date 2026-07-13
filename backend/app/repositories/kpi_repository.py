from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi import KPI


class KpiRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def record(
        self, metric_key: str, value: float, unit: str, source: str, is_estimate: bool, as_of: datetime
    ) -> KPI:
        kpi = KPI(
            metric_key=metric_key,
            value=value,
            unit=unit,
            source=source,
            is_estimate=is_estimate,
            as_of=as_of,
        )
        self.db.add(kpi)
        return kpi

    async def trend(self, metric_key: str, points: int = 12) -> list[KPI]:
        """Most recent `points` observations, oldest first (sparkline order)."""
        result = await self.db.execute(
            select(KPI)
            .where(KPI.metric_key == metric_key)
            .order_by(KPI.as_of.desc())
            .limit(points)
        )
        return list(reversed(result.scalars().all()))

    async def distinct_metric_keys(self) -> list[str]:
        result = await self.db.execute(select(KPI.metric_key).distinct())
        return [row[0] for row in result.all()]
