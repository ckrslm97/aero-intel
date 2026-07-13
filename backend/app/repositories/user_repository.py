from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, email: str, password: str, role: str = "reader") -> User:
        user = User(email=email, hashed_password=hash_password(password), role=role)
        self.db.add(user)
        await self.db.flush()
        return user
