import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_delivery import EmailDelivery


class EmailDeliveryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, subscriber_id: uuid.UUID, edition_id: uuid.UUID) -> EmailDelivery:
        result = await self.db.execute(
            select(EmailDelivery).where(
                EmailDelivery.subscriber_id == subscriber_id, EmailDelivery.edition_id == edition_id
            )
        )
        delivery = result.scalar_one_or_none()
        if delivery is not None:
            return delivery

        delivery = EmailDelivery(subscriber_id=subscriber_id, edition_id=edition_id, status="pending")
        self.db.add(delivery)
        await self.db.flush()
        return delivery

    async def list_retriable_for_edition(self, edition_id: uuid.UUID) -> list[EmailDelivery]:
        result = await self.db.execute(
            select(EmailDelivery).where(
                EmailDelivery.edition_id == edition_id,
                EmailDelivery.status.in_(["pending", "failed"]),
            )
        )
        return list(result.scalars().all())
