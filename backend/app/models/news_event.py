"""An event: one thing that happened, however many outlets reported it.

The unit of the Gazete changes here. Previously each article was its own row,
so the same story arriving from three feeds appeared three times -- and, worse,
was classified three separate times and could land in three different
categories. A measured example: `Jin Air, Air Busan and Air Seoul to merge`
was filed under `finance/equity` in English and `general` in German, from the
same event on the same day.

Classification now happens once, on the event's primary source. Secondary
sources are corroboration, and corroboration is an input to confidence rather
than a reason to render the story again.

Risk lives here rather than on the article for the same reason: an earthquake
is one risk event no matter how many outlets covered it, and the country
rollup was counting reports rather than events.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class NewsEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "news_events"
    __table_args__ = (
        # The list query: publishable events in a window, newest first.
        Index("ix_news_events_band_last_seen", "confidence_band", "last_seen"),
        Index("ix_news_events_category_last_seen", "category", "last_seen"),
        # Risk Radar reads only risk-bearing events.
        Index("ix_news_events_risk_family_last_seen", "risk_family", "last_seen"),
    )

    # --- identity -----------------------------------------------------------

    #: Stable, human-readable handle for the event, derived from the primary
    #: article's title. Used in URLs so a shared link survives a re-cluster.
    slug: Mapped[str] = mapped_column(String(220), unique=True)

    #: The Turkish headline shown to the reader. An event without one is not
    #: publishable -- see ArticleEnrichment for why untranslated rows exist.
    title_tr: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary_tr: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Highest-tier source in the cluster, earliest publication breaking ties.
    #: This is the article that was classified and the one "Kaynağa git" opens.
    #
    # use_alter: articles.event_id points here and this points back at articles,
    # so neither table can be created first. use_alter emits this constraint as
    # a separate ALTER once both exist -- without it SQLAlchemy cannot sort the
    # tables and silently skips both foreign keys when building a schema, which
    # is what the test fixtures do on every test.
    # Faz 14: indexed because Hub/Biz's per-airport and per-carrier event
    # lookups (app/services/hub_service.py, biz_service.py,
    # network_signals_service.py) all filter or join on this column -- added
    # once those callers existed, not when the column was first written,
    # which is exactly the kind of hot-path gap a query plan catches and a
    # migration diff does not.
    primary_article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "articles.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_news_events_primary_article_id",
        ),
        nullable=True,
        index=True,
    )

    # --- classification -----------------------------------------------------

    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    region: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    # --- risk ---------------------------------------------------------------
    #
    # `risk_assessed_at` is the veto made durable. A row with a timestamp and a
    # null risk_type means "a classifier looked at this and said it is not a
    # risk" -- which is different from "nobody has looked yet" (no timestamp),
    # and nothing downstream may override it. The reason the model gave is kept
    # in not_applicable_reasons so a wrong veto is diagnosable rather than
    # invisible.

    risk_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    risk_family: Mapped[str | None] = mapped_column(String(30), nullable=True)
    risk_severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    risk_country: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    risk_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: Weighted severity x probability x aviation impact x recency x source tier.
    #: Stored so the map, the ranking and the list order by the same number.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The five factors behind `risk_score`, as pipeline/risk_scoring.py
    #: computed them (severity, probability, aviation_impact, recency,
    #: source_tier). Kept for the same reason `confidence_detail` is: the score
    #: is a product of five numbers, and a bare 0.08 cannot be argued with --
    #: it does not say whether the event was minor, unlikely, stale or thinly
    #: sourced. RiskScoreResult already produced this dict and the runner threw
    #: it away; storing it is what makes a score explainable after the weights
    #: have moved on.
    risk_score_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: The classifier's own one-sentence Turkish answer to "why does aviation
    #: care about this event" (llm/classify.py RiskAssessment). Parsed on every
    #: risk call since v2 shipped and persisted nowhere until now, so the one
    #: piece of reasoning behind an aviation_impact_score was lost the moment
    #: the score was computed from it.
    aviation_impact_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- confidence ---------------------------------------------------------

    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: high | medium | low. Read endpoints serve the first two. `low` rows are
    #: kept as the record of what the pipeline chose not to show.
    confidence_band: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    #: The component breakdown that produced the score, so a judgement can be
    #: explained later even after the weights have moved on.
    confidence_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: {"risk": "entertainment_coverage", "campaign": "not_a_fare_offer", ...}
    #: Every affirmative "no" a classifier gave about this event.
    not_applicable_reasons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- cluster ------------------------------------------------------------

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: Denormalised len(articles). Every list query needs it and none of them
    #: should pay for a join to count rows.
    article_count: Mapped[int] = mapped_column(Integer, default=1)

    #: Set when a later pass supersedes this event (a re-cluster merged it into
    #: another). Kept rather than deleted so a shared link still resolves.
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    articles: Mapped[list["Article"]] = relationship(  # noqa: F821
        back_populates="event", foreign_keys="Article.event_id"
    )
