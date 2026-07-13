"""Named entities (airlines, airports, countries, routes, aircraft) extracted from articles."""
import uuid

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("entity_type", "name", name="uq_entity_type_name"),)

    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # airline|airport|country|route|aircraft
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)  # IATA/ICAO code

    article_links: Mapped[list["ArticleEntity"]] = relationship(back_populates="entity")


class ArticleEntity(Base):
    __tablename__ = "article_entities"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), primary_key=True
    )
    relevance: Mapped[float] = mapped_column(Float, default=1.0)

    article: Mapped["Article"] = relationship(back_populates="entity_links")  # noqa: F821
    entity: Mapped["Entity"] = relationship(back_populates="article_links")
