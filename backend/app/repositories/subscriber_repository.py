from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscriber import Subscriber


class SubscriberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self) -> list[Subscriber]:
        result = await self.db.execute(select(Subscriber).where(Subscriber.is_active.is_(True)))
        return list(result.scalars().all())

    async def get_by_email(self, email: str) -> Subscriber | None:
        result = await self.db.execute(select(Subscriber).where(Subscriber.email == email))
        return result.scalar_one_or_none()

    async def create(self, email: str) -> Subscriber:
        subscriber = Subscriber(email=email)
        self.db.add(subscriber)
        await self.db.flush()
        return subscriber
