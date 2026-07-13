"""A trusted data source (RSS feed, public API, or premium adapter)."""
from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1000))
    source_type: Mapped[str] = mapped_column(String(50), default="rss")  # rss | api | scrape
    category: Mapped[str] = mapped_column(String(50), default="other")  # org|airline|airport|financial|other
    trust_weight: Mapped[float] = mapped_column(Float, default=0.7)  # 0-1, used in confidence scoring
    is_premium_stub: Mapped[bool] = mapped_column(Boolean, default=False)  # needs paid credentials
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")  # noqa: F821
