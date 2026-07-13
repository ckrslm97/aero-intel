"""Portal users with role-based access (admin/editor/reader)."""
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="reader")  # admin|editor|reader
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
