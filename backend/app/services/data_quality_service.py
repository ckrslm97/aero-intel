"""Faz 13's daily data-quality job: eleven real invariants over what's actually
published, checked against the live tables rather than assumed from the code
that is supposed to enforce them upstream. Each of these was already meant to
be impossible by construction (the language gate, the confidence bands, the
required-field caps, PR2's business-class rulepacks) -- this is the
defense-in-depth check that catches a regression in that guarantee rather than
trusting it silently.

The last two look at the other end of the pipe. Everything else here asks
whether what got published is sound; `source_failure_streak` and
`silently_dead_source` ask whether anything is arriving at all. They read the
health columns app/services/ingestion_service.py writes each run, and they
exist because this codebase has already lost two regulator feeds without
noticing -- FAA and ICAO produced exactly 0 articles from the day they were
seeded, and only a manual production review ever caught it.

No custom ticketing here: `check_data_quality()` returns the violations, and
the CLI command (`app.cli evaluate-data-quality`) exits non-zero when there
are any. A failed step in a scheduled GitHub Actions run *is* the task this
opens -- the same mechanism ci.yml's taxonomy-codegen check already uses, not
a second system to keep in sync with the first.

Every check here is binary: a row either violates the invariant or it does
not. There is no WARN level, and PR8 deliberately did not add one -- a
severity a scheduled job cannot act on differently is a comment, not a
mechanism. The one check that is genuinely a *level* rather than a *defect*
(how big the manual review queue has grown) is expressed inside that
constraint, with its threshold set where "this queue is not being worked" is
the only remaining reading. See `_check_review_queue_size`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
from app.models.source import Source
from app.repositories.kpi_repository import KpiRepository
from app.services.campaign_status import campaign_status
from app.services.kpi_service import LIVE_FX_PAIRS
from app.taxonomy import CAMPAIGN_BUSINESS_CLASSES

PUBLISHABLE_BANDS = ("high", "medium")
ALLOWED_LANGUAGES = ("en", "tr")

#: How stale a live FX reading can be before the 15-minute refresh job (see
#: kpi_service.py) is considered to have actually stopped running, not just
#: mid-cycle. Set well above the 15-minute cadence so a single missed tick
#: doesn't fire a false alarm.
FX_FRESHNESS_HOURS = 24

#: The three classes taxonomy.py derives from dates ("is this campaign live")
#: rather than detecting ("is this a campaign at all"). Everything in
#: CAMPAIGN_BUSINESS_CLASSES that is *not* one of these is a row the campaign
#: timeline must never show, however confidently it was extracted.
_FARE_CAMPAIGN_CLASSES = ("ACTIVE_CAMPAIGN", "UPCOMING_CAMPAIGN", "EXPIRED_CAMPAIGN")

#: Derived from the taxonomy rather than retyped, so a class added there is
#: caught by this check by default. The failure mode of a hard-coded list is
#: silence -- a new non-fare class would publish freely until someone
#: remembered two files had to change together.
NON_FARE_BUSINESS_CLASSES: tuple[str, ...] = tuple(
    slug for slug in CAMPAIGN_BUSINESS_CLASSES if slug not in _FARE_CAMPAIGN_CLASSES
)

#: How far past its own sale_ends a still-publishable row is a retirement
#: failure rather than a feature.
#:
#: Getting this number right needs three facts. (1) agents/campaign_airline.py
#: refuses to *write* a row whose sale window closed more than
#: STALE_AFTER_DAYS (7) ago, so nothing enters the table already ancient.
#: (2) Rows age past that line by simply existing -- nothing rewrites them --
#: and that is correct: the timeline deliberately shows a campaign that just
#: closed, rendered "Süresi doldu" by services/campaign_status.py, because
#: what a rival stopped selling last week is intelligence. Flagging those
#: would be flagging the product working. (3) `mark-legacy-campaigns-
#: superseded` is the retirement mechanism, and `superseded_at` is what takes
#: a row out of every read path.
#:
#: So the violation is not "expired" and not "expired past the write guard" --
#: it is "expired so long ago that nobody would show it, and yet nothing
#: retired it". 30 days is where that becomes the only available reading: it
#: is a full month past the close, four times the write-time guard, and well
#: past any "just ended" display value, while still narrow enough that a
#: retirement failure surfaces inside a month rather than a quarter.
STALE_EXPIRED_AFTER_DAYS = 30

#: When the manual review queue stops being a queue and starts being a pile.
#:
#: The plan wanted a WARN at 25. This file has no WARN -- see the module
#: docstring -- so the choice was between inventing a severity nothing
#: consumes and setting a threshold that is unambiguous as a binary. 100 is
#: the latter: `review_required` is set at confidence < 0.75, so a healthy
#: system produces a handful a day and an analyst clears them. A hundred
#: unreviewed rows is not a busy week, it is a queue nobody is working -- and
#: that is a real operational defect, not a mood.
REVIEW_QUEUE_CEILING = 100

#: Consecutive failed ingestion runs before an active source is a defect
#: rather than a bad afternoon.
#:
#: Ingestion runs every two hours (.github/workflows/jobs-news.yml, `0 */2 *
#: * *`), so five consecutive failures is ten hours of a source returning
#: nothing usable. That is comfortably past any single publisher deploy, CDN
#: hiccup or expired certificate that fixes itself, and comfortably short of
#: the days it currently takes anyone to notice by hand.
SOURCE_FAILURE_STREAK_CEILING = 5

#: How long an active source may go without a single successful fetch before
#: it counts as silently dead.
#:
#: This is the check the codebase has already paid for: FAA and ICAO sat in
#: the seed list producing EXACTLY 0 articles from the day they were seeded,
#: and the only thing that ever caught it was a human reading production by
#: hand (see the comment in app/ingest/sources_seed.py). Seven days is chosen
#: against the SOURCES, not the schedule: the slowest feeds in the file are
#: the regulator sections, which publish every few days, and the sparsest
#: campaign radar still turns over inside a week. A source with nothing in
#: seven days is not quiet, it is broken.
#:
#: Note this catches a strictly different failure from the streak above. A
#: feed that alternates one success with four failures never reaches five in a
#: row and never trips the first check; a feed that 403s on every single run
#: trips both. The expensive case is the one only this check sees: a source
#: that has NEVER succeeded, whose last_success_at is null.
SOURCE_SILENCE_DAYS = 7


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _check_published_language(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug, Article.language)
            .join(Article, Article.id == NewsEvent.primary_article_id)
            .where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
            )
        )
    ).all()
    return [
        Violation("published_language", f"event {slug} ({event_id}): language={language!r}")
        for event_id, slug, language in rows
        if language not in ALLOWED_LANGUAGES
    ]


async def _check_no_below_threshold_published(db: AsyncSession) -> list[Violation]:
    """`is_published=True` is only meant to be set on rows the read endpoints
    would actually serve -- see NewsEvent's own confidence_band docstring
    ("low rows are kept as the record of what the pipeline chose not to
    show"). A low-band row with is_published=True would leak past that."""
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug, NewsEvent.confidence_band).where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band == "low",
                NewsEvent.superseded_at.is_(None),
            )
        )
    ).all()
    return [
        Violation("below_threshold_published", f"event {slug} ({event_id}): band=low")
        for event_id, slug, _band in rows
    ]


async def _check_no_sourceless_events(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug).where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.primary_article_id.is_(None),
            )
        )
    ).all()
    return [
        Violation("sourceless_event", f"event {slug} ({event_id}): no primary_article_id")
        for event_id, slug in rows
    ]


async def _check_no_dateless_campaigns(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(Promotion.id, Promotion.title_tr).where(
                Promotion.confidence_band.in_(PUBLISHABLE_BANDS),
                Promotion.superseded_at.is_(None),
                Promotion.sale_starts.is_(None),
                Promotion.sale_ends.is_(None),
            )
        )
    ).all()
    return [
        Violation("dateless_campaign", f"promotion {title!r} ({promo_id}): no sale window")
        for promo_id, title in rows
    ]


async def _check_no_non_fare_campaigns_published(db: AsyncSession) -> list[Violation]:
    """The single invariant the whole campaign rebuild exists to hold.

    Of 131 rows the old pipeline published, 129 were loyalty guides, product
    promos, credit-card content or plain news wearing a campaign's shape.
    PR2's rulepacks stop those at write time; this is the check that the
    rulepacks are still running -- a row that reached the publishable band
    carrying its own confession (`business_class = 'PRODUCT_PROMOTION'`) means
    the classification happened and the gate did not.
    """
    rows = (
        await db.execute(
            select(Promotion.id, Promotion.title_tr, Promotion.business_class).where(
                Promotion.confidence_band.in_(PUBLISHABLE_BANDS),
                Promotion.superseded_at.is_(None),
                Promotion.business_class.in_(NON_FARE_BUSINESS_CLASSES),
            )
        )
    ).all()
    return [
        Violation(
            "non_fare_campaign_published",
            f"promotion {title!r} ({promo_id}): business_class={business_class}",
        )
        for promo_id, title, business_class in rows
    ]


async def _check_no_stale_expired_campaigns(db: AsyncSession, *, today: date) -> list[Violation]:
    """Rows whose sale window closed a month ago and that nothing retired.

    Status is recomputed here with the same function the API and the UI use
    (services/campaign_status.py), rather than filtered in SQL, so this check
    can never disagree with what a reader sees: if the drawer says "Süresi
    doldu", this check saw EXPIRED too. See STALE_EXPIRED_AFTER_DAYS for why
    "expired" alone is not the violation.
    """
    rows = (
        await db.execute(
            select(
                Promotion.id,
                Promotion.title_tr,
                Promotion.sale_starts,
                Promotion.sale_ends,
                Promotion.travel_starts,
                Promotion.travel_ends,
            ).where(
                Promotion.confidence_band.in_(PUBLISHABLE_BANDS),
                Promotion.superseded_at.is_(None),
                Promotion.sale_ends.isnot(None),
            )
        )
    ).all()

    violations: list[Violation] = []
    for promo_id, title, sale_starts, sale_ends, travel_starts, travel_ends in rows:
        status = campaign_status(sale_starts, sale_ends, travel_starts, travel_ends, today)
        if status != "EXPIRED":
            continue
        age = (today - sale_ends).days
        if age <= STALE_EXPIRED_AFTER_DAYS:
            continue
        violations.append(
            Violation(
                "stale_expired_campaign",
                f"promotion {title!r} ({promo_id}): sale closed {sale_ends.isoformat()} "
                f"({age} days ago), still publishable and not superseded",
            )
        )
    return violations


async def _check_campaign_v2_rows_carry_a_reason(db: AsyncSession) -> list[Violation]:
    """A typed row must say why it was typed.

    `classification_reason` is the one Turkish sentence the analyst drawer
    shows under every verdict, and agents/campaign_airline.py writes it on
    *both* branches -- accept and reject alike -- precisely so no row can
    exist with a classification nobody can check. A populated campaign_type
    with a null reason means something wrote the taxonomy field around that
    function, which is the drift this catches. Not scoped to the publishable
    band: an unpublished row with an unexplained classification is the same
    audit-trail hole.
    """
    rows = (
        await db.execute(
            select(Promotion.id, Promotion.title_tr, Promotion.campaign_type).where(
                Promotion.campaign_type.isnot(None),
                Promotion.classification_reason.is_(None),
            )
        )
    ).all()
    return [
        Violation(
            "unexplained_campaign_classification",
            f"promotion {title!r} ({promo_id}): campaign_type={campaign_type} "
            f"with no classification_reason",
        )
        for promo_id, title, campaign_type in rows
    ]


async def _check_review_queue_size(db: AsyncSession) -> list[Violation]:
    """One violation, not one per row -- the queue's size is the finding."""
    pending = (
        await db.execute(
            select(func.count())
            .select_from(Promotion)
            .where(
                Promotion.review_required.is_(True),
                Promotion.superseded_at.is_(None),
            )
        )
    ).scalar_one()
    if pending <= REVIEW_QUEUE_CEILING:
        return []
    return [
        Violation(
            "review_queue_backlog",
            f"{pending} campaigns awaiting manual review "
            f"(ceiling {REVIEW_QUEUE_CEILING})",
        )
    ]


#: Health is only meaningful for sources the ingestion run actually fetches.
#: A premium stub is seeded to be *visible* in the source list until
#: credentials exist (see PREMIUM_SOURCE_NAMES in app/ingest/sources_seed.py);
#: it has no adapter, is never fetched, and would otherwise fail both checks
#: below forever for doing exactly what it was seeded to do.
_FETCHED_SOURCE = (Source.is_active.is_(True), Source.is_premium_stub.is_(False))


async def _check_source_failure_streaks(db: AsyncSession) -> list[Violation]:
    """Active sources that have failed every run for the last five runs.

    One violation per source, not per failed run: the streak is the finding.
    """
    rows = (
        await db.execute(
            select(
                Source.id,
                Source.name,
                Source.consecutive_failures,
                Source.last_http_status,
            ).where(
                *_FETCHED_SOURCE,
                Source.consecutive_failures >= SOURCE_FAILURE_STREAK_CEILING,
            )
        )
    ).all()
    return [
        Violation(
            "source_failure_streak",
            f"source {name!r} ({source_id}): {failures} consecutive failed fetches"
            + (f", last HTTP {status}" if status is not None else ", no HTTP response"),
        )
        for source_id, name, failures, status in rows
    ]


async def _check_silently_dead_sources(db: AsyncSession, *, now: datetime) -> list[Violation]:
    """Active sources with no successful fetch in the last SOURCE_SILENCE_DAYS.

    The FAA/ICAO check. Both sat in the seed list producing exactly 0 articles
    from the day they were seeded, every run logged it, and nothing added up
    the logs -- so it took a manual production review to find. This is that
    review, run daily.

    Scoped to sources that have been OBSERVED at least once (a success or a
    failure on record). A source whose health columns are entirely null has
    not been fetched since these columns existed, which is the state every row
    is in between this migration landing and the first ingestion run after it
    -- roughly a two-hour window on the `0 */2 * * *` schedule. Reporting
    ninety dead sources in that window would be reporting the deploy, not a
    defect. Once a source has any health at all, a null `last_success_at`
    stops being "not yet measured" and becomes "measured, never worked", which
    is the worst case here and the one the two lost regulators were in.
    """
    cutoff = now - timedelta(days=SOURCE_SILENCE_DAYS)
    rows = (
        await db.execute(
            select(Source.id, Source.name, Source.last_success_at).where(
                *_FETCHED_SOURCE,
                # "Has been observed": at least one recorded outcome.
                (Source.last_success_at.isnot(None)) | (Source.last_failure_at.isnot(None)),
                (Source.last_success_at.is_(None)) | (Source.last_success_at < cutoff),
            )
        )
    ).all()
    violations: list[Violation] = []
    for source_id, name, last_success_at in rows:
        if last_success_at is None:
            detail = "no successful fetch on record"
        else:
            age_days = (now - last_success_at).total_seconds() / 86400
            detail = f"last successful fetch {age_days:.1f} days ago"
        violations.append(
            Violation(
                "silently_dead_source",
                f"source {name!r} ({source_id}): {detail} "
                f"(ceiling {SOURCE_SILENCE_DAYS} days)",
            )
        )
    return violations


async def _check_fx_freshness(db: AsyncSession) -> list[Violation]:
    repo = KpiRepository(db)
    cutoff = _now() - timedelta(hours=FX_FRESHNESS_HOURS)
    violations: list[Violation] = []
    for metric_key, *_rest in LIVE_FX_PAIRS:
        latest = await repo.latest(metric_key)
        if latest is None:
            violations.append(Violation("fx_freshness", f"{metric_key}: no observation at all"))
        elif latest.as_of < cutoff:
            age_hours = (_now() - latest.as_of).total_seconds() / 3600
            violations.append(
                Violation("fx_freshness", f"{metric_key}: last reading {age_hours:.1f}h old")
            )
    return violations


async def check_data_quality(db: AsyncSession, *, today: date | None = None) -> list[Violation]:
    """`today` is injectable so the date-dependent campaign checks can be
    tested against a fixed clock; it defaults to the real one, which is what
    the scheduled job wants."""
    reference = today or _now().date()
    now = _now()
    violations: list[Violation] = []
    violations += await _check_published_language(db)
    violations += await _check_no_below_threshold_published(db)
    violations += await _check_no_sourceless_events(db)
    violations += await _check_no_dateless_campaigns(db)
    violations += await _check_no_non_fare_campaigns_published(db)
    violations += await _check_no_stale_expired_campaigns(db, today=reference)
    violations += await _check_campaign_v2_rows_carry_a_reason(db)
    violations += await _check_review_queue_size(db)
    violations += await _check_fx_freshness(db)
    violations += await _check_source_failure_streaks(db)
    violations += await _check_silently_dead_sources(db, now=now)
    return violations
