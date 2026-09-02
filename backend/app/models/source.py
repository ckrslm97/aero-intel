"""A trusted data source (RSS feed, public API, or premium adapter)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
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

    # ------------------------------------------------------------------
    # Editorial configuration. All three are declared in
    # app/ingest/sources_seed.py and written on every ensure_seeded()
    # reconcile; all three are nullable so rows seeded before this migration
    # keep working untouched.
    # ------------------------------------------------------------------
    #: very_high | high | normal | low -- how much this desk *wants* the
    #: source, which is deliberately NOT the same axis as `tier`.
    #:
    #: `tier` says what kind of publisher this is (the authority ladder:
    #: official > regulator > agency > trade > aggregator). `priority` says how
    #: much the newspaper cares about its output. The two correlate but come
    #: apart at both ends, which is the whole reason this is a second column
    #: rather than a view over the first: "Google News · Uçak Bileti Kampanya"
    #: is tier="aggregator" (lowest authority -- items come from arbitrary
    #: publishers) and yet ~100% fare-campaign content, i.e. one of the most
    #: valuable feeds in the file; "Anadolu Ajansı · Ekonomi" is tier="agency"
    #: (a national wire, genuinely authoritative) and yet mostly not aviation
    #: at all. Collapsing the two would have to lie about one of them.
    #:
    #: Seeded from the tier by default -- see TIER_DEFAULT_PRIORITY in
    #: sources_seed.py -- so the 82 sources that predate this column get a
    #: sensible value without anyone hand-typing 82 of them; the default is a
    #: starting point, and a source overrides it where the desk's judgement
    #: actually differs from the ladder.
    priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: Comma-separated app.taxonomy category slugs this source actually feeds
    #: (revenue_management, network, regulatory, ...).
    #:
    #: Named `news_categories`, not `categories`, because the column next to it
    #: called `category` means something else entirely: `category` is the
    #: INSTITUTION TYPE (org | airline | airport | financial | other -- what
    #: kind of body publishes this), while this is the NEWS BEAT (what the
    #: published items are about). A source can be category="airline" and
    #: news_categories="revenue_management,network". The near-collision is
    #: unfortunate but the alternative -- reusing one name for two taxonomies
    #: -- is how the wrong one gets read.
    #:
    #: Descriptive, not enforcing: nothing filters on it yet. It records what
    #: the build-time sampling actually found in each feed, so the next person
    #: choosing which sources to spend enrichment budget on has the answer.
    news_categories: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Intended polling interval in minutes. Informational for now: every
    #: source is fetched on the single `0 */2 * * *` schedule in
    #: .github/workflows/jobs-news.yml (120 minutes, 12 runs/day), and this
    #: column does not change that. It records the cadence a source *wants*
    #: -- a regulator that posts a legal instrument twice a month does not
    #: need the same treatment as a 100-item campaign radar -- so that a
    #: per-source scheduler has the declared intent to read when one is built.
    crawl_frequency_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------
    # Fetch health, written by app/services/ingestion_service.py on every run.
    #
    # These exist because of a failure this codebase already paid for and
    # documented: FAA and ICAO sat in the seed list producing EXACTLY 0
    # articles from the day they were seeded, and the only thing that ever
    # caught it was a human reading production by hand (see the comment in
    # app/ingest/sources_seed.py). The adapter logged the failure every run;
    # nothing accumulated it, so nothing could be asked "which sources are
    # dead?" without grepping logs nobody greps. These five columns are that
    # accumulator, and data_quality_service.py is the thing that asks.
    # ------------------------------------------------------------------
    #: Last run that returned at least one usable article.
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Last run that failed -- transport error, non-2xx, unparseable body, or
    #: a 200 that yielded no usable entries (a rotted feed is a failure, which
    #: is the same judgement rss.py's `rss_no_usable_entries` warning makes).
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: HTTP status of the last failure, when there was one. None for failures
    #: with no response at all (DNS, TLS, timeout) -- the distinction between
    #: "answered 403" and "never answered" is worth keeping.
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Consecutive failed runs; reset to 0 by any success. Not nullable in
    #: spirit -- it defaults to 0 -- but left nullable in the column so the
    #: migration is additive and pre-existing rows need no backfill.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    #: Articles the last successful run yielded. A feed whose count collapses
    #: from 40 to 1 is failing differently from one that 403s, and only this
    #: column can tell the two apart.
    last_article_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")  # noqa: F821
