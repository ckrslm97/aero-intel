"""Raw ingested articles and their AI enrichment."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_content_hash", "content_hash"),
        # The selection query for every pipeline stage: "rows in state X, oldest
        # first". Previously a sequential scan over the whole table.
        Index("ix_articles_status_fetched_at", "status", "fetched_at"),
        Index("ix_articles_search_vector", "search_vector", postgresql_using="gin"),
        # --- declared here so autogenerate stops trying to drop them ---------
        #
        # These were created by hand in d5a81c3f76e4 after GET /articles was
        # measured at 2.8s warm. Because the models never declared them,
        # `alembic revision --autogenerate` proposed DROPping all of them on the
        # next unrelated schema change -- a silent, reviewable-only-if-you-look
        # undo of a measured fix. Declaring them makes autogenerate leave them
        # alone.
        #
        # The newspaper's default query: not-duplicate, newest first.
        Index(
            "ix_articles_live_recency",
            text("published_at DESC NULLS LAST"),
            text("fetched_at DESC"),
            postgresql_where=text("is_duplicate = false"),
        ),
        # The archive's day filter and /articles/daily-counts group on
        # coalesce(published_at, fetched_at); only an expression index serves it.
        Index(
            "ix_articles_day_expr",
            text("(coalesce(published_at, fetched_at))"),
            postgresql_where=text("is_duplicate = false"),
        ),
        Index("ix_articles_source_id", "source_id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    raw_content: Mapped[str] = mapped_column(Text, default="")
    # Computed once at ingest so list endpoints never have to pull the whole
    # body out of Postgres just to show a reading time (that transfer alone was
    # hundreds of KB per request).
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # ISO 639-1, detected at ingest before anything else runs. The pipeline had
    # no idea what language an article was in, which is how 18% of the feed
    # reached a Turkish-language UI as untranslated German and Spanish. Null on
    # rows ingested before detection existed.
    language: Mapped[str | None] = mapped_column(String(5), nullable=True, index=True)

    #: The event this article belongs to. Several articles share one event when
    #: they report the same thing; the event carries the classification.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="SET NULL"), nullable=True
    )

    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 of normalized title+body
    # populated from title+headline+summary once enriched; title-only right after ingestion
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # new -> deduped -> enriched ; or duplicate (points at the canonical article)
    #
    # v2 adds the rejection states. They exist so a rejected article is a fact
    # with a reason attached rather than an absence: "why is this not in the
    # paper" used to be unanswerable.
    #   rejected_language  not English or Turkish
    #   rejected_gate      failed the aviation-relevance gate before any LLM call
    #   enrich_pending     cleared the gate, awaiting classification
    #   enrich_failed      the classifier did not answer; retried, never published
    status: Mapped[str] = mapped_column(String(20), default="new")
    #: Machine-readable reason for a rejected_* status, e.g. "language:de",
    #: "no_aviation_terms", "listicle". Aggregated to answer what the gate is
    #: actually filtering, so a too-strict rule is visible instead of silent.
    rejection_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), nullable=True
    )

    source: Mapped["Source"] = relationship(back_populates="articles")  # noqa: F821
    event: Mapped["NewsEvent | None"] = relationship(  # noqa: F821
        back_populates="articles", foreign_keys=[event_id]
    )
    enrichment: Mapped["ArticleEnrichment | None"] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )
    entity_links: Mapped[list["ArticleEntity"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan"
    )


class ArticleEnrichment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-to-one AI-derived fields for an article, kept separate so re-enrichment never touches raw data."""

    __tablename__ = "article_enrichment"
    __table_args__ = (
        # Category, subcategory and region arrive together from the filter rows;
        # three single-column indexes force a bitmap AND. Declared here for the
        # same reason as the article indexes above -- so autogenerate leaves the
        # hand-written index alone.
        Index("ix_enrichment_cat_sub_region", "category", "subcategory", "region"),
        # Declared here for the same reason the article indexes above are:
        # an index the models do not know about is one
        # `alembic revision --autogenerate` proposes DROPping on the next
        # unrelated schema change.
        Index("ix_article_enrichment_intelligence_score", "intelligence_score"),
        Index(
            "ix_article_enrichment_promo_pending",
            "article_id",
            postgresql_where=text("promo_extracted_at IS NULL"),
        ),
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id"), unique=True
    )
    headline: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    # second-level taxonomy slug within `category` -- see app/taxonomy.py; null
    # for categories that have no subcategories defined (safety, regulatory, ...)
    subcategory: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # world-region slug detected from country entities, see app/taxonomy.py
    # COUNTRY_TO_REGION -- null when no country was detected in the article
    region: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1, drives Top-10

    # --- intelligence score (see app/services/news_scoring.py) ---------------
    #
    # importance_score above does not measure importance. With
    # corroborating_source_count == 1 -- which is every article in production --
    # its formula reduces to `0.34 + 0.21 * source.trust_weight`, so it is a
    # restatement of which outlet published the story: eighteen sources produced
    # eight distinct values across the whole archive, one value each. Raising a
    # threshold on it selects publishers, not stories.
    #
    # intelligence_score replaces it for the Gazete's "fewer, more critical
    # stories" filter. Both columns are kept: importance_score is still read by
    # the frontend, by edition_service.py and by every existing min_importance
    # caller, and swapping them in one deploy would leave no way to compare the
    # two rankings. The frontend migration is a separate change.
    # Indexed via the named Index in __table_args__ above, not `index=True`
    # here -- declaring both would create two indexes on one column.
    intelligence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The eight components and the weights that combined them, so a score
    #: stays explainable after the weights have moved on -- the same reason
    #: promotions.confidence_detail is stored rather than recomputed.
    score_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: The model's three impact axes, 0-1, written only for the day's shortlist
    #: (app/services/critical_selection.py).
    #:
    #: NULL IS LOAD-BEARING AND IS NOT 0.0. NULL means the selection pass did
    #: not spend a call on this article; 0.0 means the model read it and found
    #: no impact on that axis. news_scoring.combine() renormalises its weights
    #: over the components that are present, so the distinction is what lets a
    #: deterministic-only score be compared with an LLM-scored one at all.
    #: Defaulting these to 0.0 would erase it -- and would make every article
    #: nobody looked at indistinguishable from one the model rejected.
    rm_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    demand_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity_impact: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: When app/pipeline/promotions.py last ran campaign extraction for this
    #: article -- set whether or not a campaign was found.
    #:
    #: The guard against a measured production leak: `_candidate_articles` had
    #: no memory of what it had already read, so the :10/:40 cron re-sent every
    #: matching article in the ARCHIVE to the LLM 48 times a day, forever. The
    #: extractor's own comment already conceded the behaviour ("re-reads the
    #: same article text every 30 minutes with an LLM whose answer is not stable
    #: to the field"). This is the column that stops it.
    promo_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")  # positive|neutral|negative
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)  # cross-source verification, 0-1
    corroborating_source_count: Mapped[int] = mapped_column(default=1)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_provider_used: Mapped[str] = mapped_column(String(30), default="heuristic")
    tags: Mapped[str] = mapped_column(String(500), default="")  # comma-separated for simplicity

    # Turkish translation, populated only when a translation-capable LLM
    # provider is configured (see app/llm/base.py translate()). Both null when
    # no LLM ran -- the API then honestly reports is_translated=False and the
    # frontend falls back to the (English) headline/summary above.
    headline_tr: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_tr: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    translation_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)

    #: "Neden önemli?" -- one or two Turkish sentences on what this story means
    #: for a revenue-management desk, written by the LLM at enrichment time.
    #:
    #: NULL on the overwhelming majority of rows and that is the design, not a
    #: backlog: it is generated only for articles whose focus-weighted
    #: importance clears WHY_IMPORTANT_MIN_IMPORTANCE (app/pipeline/enrich.py)
    #: AND only when a translation-capable live provider is configured, because
    #: it is a second model call on top of translation and translation already
    #: is the daily token budget. A handful of articles a day carry one; the UI
    #: shows the block when it is there and nothing at all when it is not.
    #:
    #: Text, not String(n): a length cap would truncate a sentence mid-word
    #: rather than reject it. The provider caps its own answer instead.
    why_important_tr: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Risk Radarı classification (see app/taxonomy.py RISK_TYPES) ---------
    # All nullable, and null is the overwhelmingly common case: most aviation
    # articles are not disaster or conflict events. Kept on ArticleEnrichment
    # rather than Article because it is a derived judgement about the story,
    # not a fact about the fetched document -- so a re-enrichment pass may
    # freely change or clear it without touching raw data.
    #
    # risk_family is stored rather than derived from risk_type on read so the
    # /risks endpoint can filter and group on it in SQL. It is written only
    # through app.taxonomy.risk_family_of(), so the two can never disagree.
    risk_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    risk_family: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    risk_severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    risk_country: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    # Frequently null even when risk_country is set -- see the note in
    # app/llm/heuristic.py detect_risk_place() on how limited city resolution
    # is without a full airport/city reference dataset.
    risk_city: Mapped[str | None] = mapped_column(String(80), nullable=True)

    article: Mapped["Article"] = relationship(back_populates="enrichment")
