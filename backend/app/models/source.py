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
    #: One of pipeline/confidence.py's five discrete tiers (official | regulator
    #: | agency | trade | aggregator) -- the owner's source priority ladder,
    #: declared per source rather than bridged from trust_weight at read time.
    #: Nullable so v1 rows (seeded before this column existed) fall back to the
    #: same trust_weight bucketing app/agents/runner.py used before this field
    #: existed, rather than erroring on a null tier.
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: ISO 639-1, declared for the same reason app/agents/base.py's SourceSpec
    #: carries one: the feed list is curated and finite, so this is usually
    #: already known and needs no per-article inference. None means mixed or
    #: unknown -- pipeline/language.py falls back to detection.
    language: Mapped[str | None] = mapped_column(String(5), nullable=True)
    is_premium_stub: Mapped[bool] = mapped_column(Boolean, default=False)  # needs paid credentials
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")  # noqa: F821
