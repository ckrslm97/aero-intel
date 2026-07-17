"""A daily newspaper edition: an ordered, sectioned snapshot of articles."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
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
    # Set when the PDF bytes land in `edition_pdfs`. Kept here (rather than
    # joining) so listing editions never has to touch the blob table.
    pdf_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    articles: Mapped[list["EditionArticle"]] = relationship(
        back_populates="edition", cascade="all, delete-orphan", order_by="EditionArticle.rank"
    )
    pdf: Mapped["EditionPdf | None"] = relationship(
        back_populates="edition", uselist=False, cascade="all, delete-orphan"
    )


class EditionPdf(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The rendered PDF, stored in Postgres rather than on disk.

    The app runs on a serverless platform with a read-only, ephemeral
    filesystem, and the PDF is produced by a separate GitHub Actions runner --
    two machines that share nothing but the database. So the database is the
    only place both sides can meet.
    """

    __tablename__ = "edition_pdfs"

    edition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editions.id", ondelete="CASCADE"), unique=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
    byte_size: Mapped[int] = mapped_column(Integer)

    edition: Mapped["Edition"] = relationship(back_populates="pdf")


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
