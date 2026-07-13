from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity


class EntityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, entity_type: str, name: str, code: str | None) -> Entity:
        result = await self.db.execute(
            select(Entity).where(Entity.entity_type == entity_type, Entity.name == name)
        )
        entity = result.scalar_one_or_none()
        if entity is not None:
            return entity

        entity = Entity(entity_type=entity_type, name=name, code=code)
        self.db.add(entity)
        await self.db.flush()
        return entity
