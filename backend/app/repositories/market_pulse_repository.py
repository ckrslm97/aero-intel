from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_pulse import MarketPulse


class MarketPulseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def record(self, summary_tr: str, citations: list[dict], generated_at: datetime) -> MarketPulse:
        pulse = MarketPulse(summary_tr=summary_tr, citations=citations, generated_at=generated_at)
        self.db.add(pulse)
        return pulse

    async def latest(self) -> MarketPulse | None:
        result = await self.db.execute(
            select(MarketPulse).order_by(MarketPulse.generated_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()
