"""Newsletter subscribers."""
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Subscriber(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscribers"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
