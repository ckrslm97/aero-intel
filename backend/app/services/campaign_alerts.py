"""Turning campaign rows into the five things worth interrupting someone about.

What this is, and what it deliberately is not
--------------------------------------------
Everything else on the campaign surface is derived at read time: the status, the
Turkish date ranges, the analyst table's filters. An alert is the one campaign
object that gets *stored*, because it is a notification rather than a fact, and
the only interesting property of a notification is that it fires exactly once.

Which is hard here, for reasons that are properties of this deployment rather
than of alerting in general:

* GitHub's scheduler is measured 2-2.75 hours late on this repo. A rule like
  "warn three days before the sale ends" evaluated against a clock will skip a
  campaign whose window closes inside a delayed run's blind spot.
* The generator is called from two workflows on purpose (the deep scan and the
  daily data-quality job), so the *normal* case is being run more than once a
  day with the same input.
* A manual `workflow_dispatch` can add a third run inside the same hour.

So every rule below is written as a query over *state*, never over "what
changed since I last looked", and every alert carries a `dedupe_key` whose
bucket is a property of the campaign rather than of the clock -- the day it was
first seen, the version number of the edit, the `sale_ends` date being warned
about. Run this function once, twice or five times on the same day and the
second and later runs write nothing; skip a day entirely and nothing is lost,
because the next run re-derives the same keys and finds the same gaps.

The first-run flood guard
-------------------------
A stateless "query over state" design has one failure mode, and it bites
exactly once: the first run sees the entire table's history at once. Two
hundred legacy campaigns whose sale windows closed in 2024 would all qualify as
EXPIRED and produce two hundred alerts nobody wants to read on day one.

Every rule is therefore bounded by a small window around today -- 48 hours of
first-sightings for NEW and LOW_CONFIDENCE, 48 hours of version rows for
CHANGE, and a few days either side of today's date for EXPIRING and EXPIRED.
The bound is not an optimisation; it is what makes the first run's output the
same size as every later run's.

The priority matrix
-------------------
Four boosts, counted, then mapped to a level. They are the four properties that
make a campaign a competitive event rather than a listing:

    boost                          why it matters
    ------------------------------ ------------------------------------------
    carrier in RIVAL_CODES         a named rival moving is the whole product
    discount_pct >= 40             deep enough to move share, not a teaser
    campaign_type == FLASH_SALE    short-lived; late notice is no notice
    booking window <= 7 days       the reaction window is measured in days

    boosts   priority (ordinary alert)   priority (LOW_CONFIDENCE alert)
    ------   -------------------------   -------------------------------
    0        MEDIUM                      INFO
    1        HIGH                        MEDIUM
    >= 2     CRITICAL                    HIGH

LOW_CONFIDENCE sits one rung lower across the whole ladder because of what it
means: the extraction itself is not trusted yet. A row we are not sure about
must never reach CRITICAL, however rival-shaped it looks -- CRITICAL on an
unreviewed row trains the reader to ignore CRITICAL. Boosts still lift it,
because an unreviewed *QR flash sale* is worth a look before an unreviewed
listing is.

Nothing here calls an LLM, fetches a page, or writes to `promotions`. It reads
campaign state and appends to `campaign_alerts`; that is the entire blast
radius.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.promotions import _publishable_promotions
from app.core.logging import get_logger
from app.core.tr_dates import format_short_date
from app.models.campaign_alert import (
    ALERT_PRIORITY_LABELS_TR,
    ALERT_TYPES,
    CampaignAlert,
)
from app.models.campaign_version import CampaignVersion
from app.models.promotion import NEW_WINDOW_HOURS, Promotion
from app.services.campaign_status import campaign_status
from app.taxonomy import RIVAL_CODES

logger = get_logger(__name__)

#: How far ahead of `sale_ends` the "bitmek üzere" warning fires. Three days is
#: the shortest horizon that survives a 2-3 hour cron delay on both of the two
#: daily runs and still leaves a working day to react in.
EXPIRING_WITHIN_DAYS = 3

#: How far back EXPIRED looks. A campaign that ended last week is not news, and
#: a campaign that ended in 2024 is the first-run flood. Three days means a
#: weekend of skipped runs still catches every expiry exactly once.
EXPIRED_LOOKBACK_DAYS = 3

#: The deep discount threshold, in percent. Below this a campaign is a
#: promotion; at or above it, it is a price move.
DEEP_DISCOUNT_PCT = 40

#: A sale window this short or shorter is a boost on its own: by the time a
#: weekly review notices it, it is over.
SHORT_BOOKING_WINDOW_DAYS = 7

#: `title_tr` is String(300); composed sentences are trimmed to fit rather than
#: risking a write that fails on a long carrier campaign name.
TITLE_MAX_CHARS = 300

#: Which changed field a CHANGE alert leads with when an edit touched several.
#: Ordered by what a revenue desk reacts to: the sale window closing early is
#: an action item, a retitled campaign is not.
_CHANGE_FIELD_PRIORITY: tuple[str, ...] = (
    "sale_ends",
    "sale_starts",
    "discount_pct",
    "travel_ends",
    "travel_starts",
    "campaign_type",
    "business_class",
    "ond",
    "route_scope",
    "markets",
    "title_tr",
    "summary_tr",
)

#: Turkish names for the fields a CHANGE alert can be about. A field with no
#: entry here is skipped as the *headline* of an alert (it still travels in
#: detail_json): an alert reading "kampanyada evidence_json değişti" is noise.
_CHANGE_FIELD_LABELS_TR: dict[str, str] = {
    "sale_starts": "satış başlangıcı",
    "sale_ends": "satış bitişi",
    "travel_starts": "seyahat başlangıcı",
    "travel_ends": "seyahat bitişi",
    "discount_pct": "indirim oranı",
    "campaign_type": "kampanya türü",
    "business_class": "kampanya sınıfı",
    "ond": "rota",
    "route_scope": "rota kapsamı",
    "markets": "pazarlar",
    "title_tr": "kampanya başlığı",
    "summary_tr": "kampanya özeti",
}

_DATE_FIELDS = frozenset(
    {"sale_starts", "sale_ends", "travel_starts", "travel_ends", "page_published_at", "page_updated_at"}
)


# --- priority ---------------------------------------------------------------


def _boosts(promotion: Promotion) -> list[str]:
    """Which of the four escalation reasons apply. Named, not counted, because
    the names go into `detail_json` -- "why is this CRITICAL" has to be
    answerable from the stored row alone."""
    reasons: list[str] = []
    if promotion.airline_code in RIVAL_CODES:
        reasons.append("rival_carrier")
    if promotion.discount_pct is not None and promotion.discount_pct >= DEEP_DISCOUNT_PCT:
        reasons.append("deep_discount")
    if promotion.campaign_type == "FLASH_SALE":
        reasons.append("flash_sale")
    if (
        promotion.sale_starts is not None
        and promotion.sale_ends is not None
        and (promotion.sale_ends - promotion.sale_starts).days <= SHORT_BOOKING_WINDOW_DAYS
    ):
        reasons.append("short_booking_window")
    return reasons


def _priority(promotion: Promotion, alert_type: str) -> tuple[str, list[str]]:
    """(priority, boost names) per the matrix in the module docstring."""
    reasons = _boosts(promotion)
    ladder = ("INFO", "MEDIUM", "HIGH") if alert_type == "LOW_CONFIDENCE" else ("MEDIUM", "HIGH", "CRITICAL")
    return ladder[min(len(reasons), 2)], reasons


# --- Turkish composition ----------------------------------------------------


def _trim(text: str) -> str:
    if len(text) <= TITLE_MAX_CHARS:
        return text
    return text[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def _format_change_value(field: str, value: Any) -> str:
    """A diff value as a reader sees it.

    `campaign_versions.changed_fields` stores dates as ISO strings (see
    promo_dedup._jsonable), so a date has to be parsed back before it can be
    written the Turkish way -- printing "2026-10-31" in a Turkish sentence is
    the kind of leak this codebase formats dates centrally to avoid.
    """
    if value is None or value == "":
        return "belirtilmemiş"
    if field in _DATE_FIELDS and isinstance(value, str):
        try:
            return format_short_date(date.fromisoformat(value[:10]))
        except ValueError:
            return str(value)
    if field == "discount_pct":
        return f"%{value}"
    text = str(value)
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _lead_change(changed_fields: dict) -> str | None:
    """The one field a CHANGE alert's sentence is about, or None when the edit
    touched nothing a reader would recognise (a re-scored confidence, a
    refreshed evidence blob). Those edits are real and are kept in the version
    table; they are simply not worth a notification."""
    for field in _CHANGE_FIELD_PRIORITY:
        if field in changed_fields:
            return field
    return None


def _days_phrase(days: int) -> str:
    if days <= 0:
        return "bugün bitiyor"
    if days == 1:
        return "yarın bitiyor"
    return f"{days} gün sonra bitiyor"


# --- the rules --------------------------------------------------------------


def _base_detail(promotion: Promotion) -> dict:
    """What every alert carries about its campaign, so the mail, the strip and
    the API never have to join back to `promotions` just to name a carrier."""
    return {
        "airline_code": promotion.airline_code,
        "airline_name": promotion.airline_name,
        "campaign_title": promotion.title_tr,
        "url": promotion.url,
        "campaign_type": promotion.campaign_type,
        "discount_pct": promotion.discount_pct,
        "sale_starts": promotion.sale_starts.isoformat() if promotion.sale_starts else None,
        "sale_ends": promotion.sale_ends.isoformat() if promotion.sale_ends else None,
    }


def _alert_row(
    promotion: Promotion,
    *,
    alert_type: str,
    bucket: str,
    title_tr: str,
    detail: dict | None = None,
) -> dict:
    priority, reasons = _priority(promotion, alert_type)
    payload = {**_base_detail(promotion), "priority_boosts": reasons}
    if detail:
        payload.update(detail)
    return {
        "id": uuid.uuid4(),
        "promotion_id": promotion.id,
        "alert_type": alert_type,
        "priority": priority,
        "title_tr": _trim(title_tr),
        "detail_json": payload,
        "dedupe_key": f"{promotion.id}:{alert_type}:{bucket}",
    }


async def _new_campaigns(db: AsyncSession, *, now: datetime) -> list[dict]:
    """Publishable campaigns first seen inside the 48h "Yeni" window.

    The same window the page's own "Son 48 saatte N yeni kampanya" banner uses
    (`NEW_WINDOW_HOURS`), so a campaign cannot be new on the page and silent in
    the alert list. Legacy rows have `first_seen_at` backfilled from
    `detected_at` by Migration A, which is what keeps them out of here.
    """
    cutoff = now - timedelta(hours=NEW_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(Promotion).where(
                _publishable_promotions(),
                Promotion.first_seen_at.isnot(None),
                Promotion.first_seen_at >= cutoff,
            )
        )
    ).scalars().all()

    alerts = []
    for promotion in rows:
        bucket = promotion.first_seen_at.date().isoformat()
        alerts.append(
            _alert_row(
                promotion,
                alert_type="NEW",
                bucket=bucket,
                title_tr=f"Yeni kampanya — {promotion.airline_name}: {promotion.title_tr}",
            )
        )
    return alerts


async def _changed_campaigns(db: AsyncSession, *, now: datetime) -> list[dict]:
    """One alert per version row written in the last 48 hours.

    Keyed on the version number rather than on a "since I last ran" timestamp:
    version numbers are dense and immutable per campaign, so the same edit
    computes the same key forever and a re-run cannot double-report it. The 48h
    bound is the flood guard -- it means the first run reports the last two
    days of edits, not the entire version history.
    """
    cutoff = now - timedelta(hours=NEW_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(CampaignVersion, Promotion)
            .join(Promotion, Promotion.id == CampaignVersion.promotion_id)
            .where(_publishable_promotions(), CampaignVersion.created_at >= cutoff)
            .order_by(CampaignVersion.created_at)
        )
    ).all()

    alerts = []
    for version, promotion in rows:
        changed = version.changed_fields or {}
        field = _lead_change(changed)
        if field is None:
            continue
        entry = changed[field] or {}
        previous = _format_change_value(field, entry.get("previous"))
        current = _format_change_value(field, entry.get("new"))
        label = _CHANGE_FIELD_LABELS_TR[field]
        sentence = (
            f"{promotion.airline_name} kampanyasında {label} değişti: {previous} → {current}"
        )
        others = sum(1 for name in changed if name != field and name in _CHANGE_FIELD_LABELS_TR)
        if others:
            sentence += f" (+{others} alan daha)"
        alerts.append(
            _alert_row(
                promotion,
                alert_type="CHANGE",
                bucket=f"v{version.version_no}",
                title_tr=sentence,
                detail={
                    "version_no": version.version_no,
                    "changed_field": field,
                    "changed_fields": sorted(changed),
                    "previous": entry.get("previous"),
                    "new": entry.get("new"),
                    "conflict": bool(entry.get("conflict")),
                },
            )
        )
    return alerts


async def _expiring_campaigns(db: AsyncSession, *, today: date) -> list[dict]:
    """Campaigns whose booking window closes within three days.

    Bucketed on `sale_ends`, not on "days left": a run that arrives two hours
    late, or a day late, computes the same key for the same campaign and so
    still fires exactly once -- and the day-count in the sentence is recomputed
    from whenever it actually ran, so it is never wrong even when the run is.
    """
    horizon = today + timedelta(days=EXPIRING_WITHIN_DAYS)
    rows = (
        await db.execute(
            select(Promotion).where(
                _publishable_promotions(),
                Promotion.sale_ends.isnot(None),
                Promotion.sale_ends >= today,
                Promotion.sale_ends <= horizon,
            )
        )
    ).scalars().all()

    alerts = []
    for promotion in rows:
        status = campaign_status(
            promotion.sale_starts,
            promotion.sale_ends,
            promotion.travel_starts,
            promotion.travel_ends,
            today,
        )
        # An UPCOMING campaign whose sale window opens and shuts inside three
        # days is not "bitmek üzere" -- it has not started. It gets its NEW
        # alert instead, and lands here on the day it opens.
        if status != "ACTIVE_BOOKING":
            continue
        days_left = (promotion.sale_ends - today).days
        alerts.append(
            _alert_row(
                promotion,
                alert_type="EXPIRING",
                bucket=promotion.sale_ends.isoformat(),
                title_tr=(
                    f"{promotion.airline_name} kampanyası {_days_phrase(days_left)}: "
                    f"{promotion.title_tr}"
                ),
                detail={"days_left": days_left, "status": status},
            )
        )
    return alerts


async def _expired_campaigns(db: AsyncSession, *, today: date) -> list[dict]:
    """Campaigns whose sale window closed in the last few days.

    The natural rule is "sale_ends == yesterday", and it is wrong here: a
    skipped or delayed run would drop that day's expiries on the floor for
    good. A short lookback plus a `sale_ends`-keyed bucket gives the same "once
    per campaign" guarantee while surviving a missed run -- and bounds the
    first run, which would otherwise announce every campaign that ever ended.
    """
    floor = today - timedelta(days=EXPIRED_LOOKBACK_DAYS)
    rows = (
        await db.execute(
            select(Promotion).where(
                _publishable_promotions(),
                Promotion.sale_ends.isnot(None),
                Promotion.sale_ends >= floor,
                Promotion.sale_ends < today,
            )
        )
    ).scalars().all()

    alerts = []
    for promotion in rows:
        alerts.append(
            _alert_row(
                promotion,
                alert_type="EXPIRED",
                bucket=promotion.sale_ends.isoformat(),
                title_tr=(
                    f"{promotion.airline_name} kampanyası sona erdi "
                    f"({format_short_date(promotion.sale_ends)}): {promotion.title_tr}"
                ),
                detail={
                    "status": campaign_status(
                        promotion.sale_starts,
                        promotion.sale_ends,
                        promotion.travel_starts,
                        promotion.travel_ends,
                        today,
                    )
                },
            )
        )
    return alerts


async def _low_confidence_campaigns(db: AsyncSession, *, now: datetime) -> list[dict]:
    """Newly-extracted rows the confidence layer flagged for a human.

    Deliberately *not* filtered through `_publishable_promotions()`: a row is
    flagged precisely because it scored badly, and a bad score is often a low
    confidence band, which is exactly what that filter excludes. Filtering here
    would mean the review queue's alert never fires for the rows most in need
    of review. Superseded rows are still excluded -- those are decided.
    """
    cutoff = now - timedelta(hours=NEW_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(Promotion).where(
                Promotion.superseded_at.is_(None),
                Promotion.review_required.is_(True),
                Promotion.first_seen_at.isnot(None),
                Promotion.first_seen_at >= cutoff,
            )
        )
    ).scalars().all()

    alerts = []
    for promotion in rows:
        alerts.append(
            _alert_row(
                promotion,
                alert_type="LOW_CONFIDENCE",
                bucket=promotion.first_seen_at.date().isoformat(),
                title_tr=(
                    f"İnceleme gerekiyor — {promotion.airline_name}: {promotion.title_tr}"
                ),
                detail={
                    "confidence_score": promotion.confidence_score,
                    "confidence_band": promotion.confidence_band,
                    "classification_reason": promotion.classification_reason,
                },
            )
        )
    return alerts


# --- the entry point --------------------------------------------------------


async def generate_alerts(
    db: AsyncSession, *, today: date | None = None, now: datetime | None = None
) -> dict:
    """Write every alert today's campaign state calls for. Idempotent.

    Returns a counter per alert type plus `total` (rows actually written) and
    `duplicates` (rows the dedupe key had already covered) -- on a healthy
    second run of the same day, `total` is 0 and `duplicates` is everything.

    `today` and `now` are injectable so the date-bucketing can be tested
    against a "delayed cron" without freezing the process clock; production
    passes neither.
    """
    now = now or datetime.now(timezone.utc)
    today = today or now.date()

    candidates: list[dict] = []
    candidates += await _new_campaigns(db, now=now)
    candidates += await _changed_campaigns(db, now=now)
    candidates += await _expiring_campaigns(db, today=today)
    candidates += await _expired_campaigns(db, today=today)
    candidates += await _low_confidence_campaigns(db, now=now)

    counts = {alert_type: 0 for alert_type in ALERT_TYPES}
    summary = {**counts, "total": 0, "duplicates": 0}
    if not candidates:
        return summary

    # ON CONFLICT DO NOTHING resolves collisions against rows already in the
    # table, but Postgres refuses a statement that would touch the same row
    # twice, so the batch has to be unique before it is sent. Two rules can
    # legitimately produce the same key in one run only if a bucket is buggy --
    # keeping the first is the safe reading either way.
    unique: dict[str, dict] = {}
    for row in candidates:
        unique.setdefault(row["dedupe_key"], row)
    rows = list(unique.values())

    written = (
        await db.execute(
            pg_insert(CampaignAlert)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(CampaignAlert.dedupe_key)
        )
    ).scalars().all()
    await db.commit()

    written_keys = set(written)
    for row in rows:
        if row["dedupe_key"] in written_keys:
            summary[row["alert_type"]] += 1
    summary["total"] = len(written_keys)
    summary["duplicates"] = len(rows) - len(written_keys)

    logger.info("campaign_alerts_generated", **summary)
    return summary


# --- the daily mail's section ----------------------------------------------


async def recent_alert_highlights(
    db: AsyncSession,
    *,
    hours: int = 24,
    limit: int = 6,
    now: datetime | None = None,
) -> list[dict]:
    """The last day's CRITICAL and HIGH alerts, shaped for the newsletter.

    Only the two top levels: the mail is a digest, and a MEDIUM alert is
    something to find on the page rather than something to be told over
    breakfast. Returns an empty list when there is nothing, and the template
    renders no section at all in that case -- an empty "Kampanya Radarı"
    heading every quiet day is how a reader learns to skip the section.
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(CampaignAlert, Promotion.airline_name, Promotion.airline_code)
            .join(Promotion, Promotion.id == CampaignAlert.promotion_id)
            .where(
                CampaignAlert.created_at >= now - timedelta(hours=hours),
                CampaignAlert.priority.in_(("CRITICAL", "HIGH")),
                CampaignAlert.acknowledged_at.is_(None),
            )
            .order_by(CampaignAlert.priority.desc(), CampaignAlert.created_at.desc())
            .limit(limit)
        )
    ).all()

    # "CRITICAL" sorts before "HIGH" alphabetically, which is the order we
    # want, but relying on that would break the day a priority is renamed --
    # so the final ordering is done here against the declared level order.
    ordered = sorted(rows, key=lambda r: (0 if r[0].priority == "CRITICAL" else 1))
    return [
        {
            "title_tr": alert.title_tr,
            "priority": alert.priority,
            "priority_label": ALERT_PRIORITY_LABELS_TR.get(alert.priority, alert.priority),
            "airline_name": airline_name,
            "airline_code": airline_code,
        }
        for alert, airline_name, airline_code in ordered
    ]
