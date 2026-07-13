"""Delivery log for each (subscriber, edition) newsletter send attempt -- supports retry + audit."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class EmailDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_deliveries"

    subscriber_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscribers.id"))
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("editions.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
