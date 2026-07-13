"""A daily newspaper edition: an ordered, sectioned snapshot of articles."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Edition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "editions"

    edition_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published
    headline: Mapped[str] = mapped_column(String(500), default="")
    executive_summary: Mapped[str] = mapped_column(String(2000), default="")
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    articles: Mapped[list["EditionArticle"]] = relationship(
        back_populates="edition", cascade="all, delete-orphan", order_by="EditionArticle.rank"
    )


class EditionArticle(Base):
    __tablename__ = "edition_articles"
    __table_args__ = (UniqueConstraint("edition_id", "article_id", name="uq_edition_article"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("editions.id"))
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("articles.id"))
    section: Mapped[str] = mapped_column(String(50), default="general")  # top_story|finance|regional|...
    rank: Mapped[int] = mapped_column(Integer, default=0)

    edition: Mapped["Edition"] = relationship(back_populates="articles")
    article: Mapped["Article"] = relationship()  # noqa: F821
