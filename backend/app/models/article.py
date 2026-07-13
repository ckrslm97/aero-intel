"""Raw ingested articles and their AI enrichment."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_content_hash", "content_hash"),
        Index("ix_articles_search_vector", "search_vector", postgresql_using="gin"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    raw_content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 of normalized title+body
    # populated from title+headline+summary once enriched; title-only right after ingestion
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # status: new -> deduped -> enriched ; or duplicate (points at the canonical article)
    status: Mapped[str] = mapped_column(String(20), default="new")
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), nullable=True
    )

    source: Mapped["Source"] = relationship(back_populates="articles")  # noqa: F821
    enrichment: Mapped["ArticleEnrichment | None"] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )
    entity_links: Mapped[list["ArticleEntity"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan"
    )


class ArticleEnrichment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-to-one AI-derived fields for an article, kept separate so re-enrichment never touches raw data."""

    __tablename__ = "article_enrichment"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), unique=True
    )
    headline: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1, drives Top-10
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")  # positive|neutral|negative
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)  # cross-source verification, 0-1
    corroborating_source_count: Mapped[int] = mapped_column(default=1)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_provider_used: Mapped[str] = mapped_column(String(30), default="heuristic")
    tags: Mapped[str] = mapped_column(String(500), default="")  # comma-separated for simplicity

    article: Mapped["Article"] = relationship(back_populates="enrichment")
