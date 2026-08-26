"""Named entities (airlines, airports, countries, routes, aircraft) extracted from articles."""
import uuid

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("entity_type", "name", name="uq_entity_type_name"),
        # Entity.code had no index despite `code IN (...)` running on every
        # rival-airline click. Declared so autogenerate leaves it alone.
        Index("ix_entities_type_code", "entity_type", "code"),
    )

    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # airline|airport|country|route|aircraft
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)  # IATA/ICAO code

    article_links: Mapped[list["ArticleEntity"]] = relationship(back_populates="entity")


class ArticleEntity(Base):
    __tablename__ = "article_entities"
    __table_args__ = (
        # The airline filter joins entity -> article; the primary key is
        # (article_id, entity_id) and cannot serve that direction. Declared
        # so autogenerate does not propose dropping it.
        Index("ix_article_entities_entity", "entity_id", "article_id"),
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), primary_key=True
    )
    relevance: Mapped[float] = mapped_column(Float, default=1.0)

    article: Mapped["Article"] = relationship(back_populates="entity_links")  # noqa: F821
    entity: Mapped["Entity"] = relationship(back_populates="article_links")
