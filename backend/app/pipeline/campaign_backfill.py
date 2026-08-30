"""Re-asking "is this a fare campaign?" of rows written before the rules existed.

The campaign rebuild put a business-class gate in front of every *new* row
(agents/campaign_airline.py): a page about miles, baggage, a standing student
rate or someone else's campaign never becomes a published promotion. What it
could not do is reach backwards. The `promotions` table still carries the rows
the v1 pipeline wrote, and the quality-gate measurement found 14 of 99 observed
golden records would still publish today -- credit-card and points content,
award-search subscriptions, rail tickets, service announcements, cargo
financials. They are on the live page right now under headlines like "Citi
ThankYou Puanlarınızı Turkish Airlines'a Aktarın" and "Buy Qatar Airways Avios
With 50% Bonus", and the alert generator has been dutifully telling readers
when those "campaigns" expire.

So this is the campaign surface's equivalent of
`enrich.backfill_risk_classification`: one heuristic-only, LLM-free pass over
what is already stored, applying today's rules to yesterday's rows. Zero model
calls is not a cost optimisation here -- it is what makes the pass *auditable*.
Every retirement below can be reproduced from the row's own text and the
keyword tables in campaign_airline.py, and re-running it a month from now on
the same data gives the same answer.

Retire, never delete
--------------------
A detected non-fare row gets `superseded_at`, exactly as
`promo_dedup.mark_legacy_campaigns_superseded` does: the read path filters on
that column (api/v1/promotions.py `_publishable_promotions`), so the row leaves
the published surface while staying in the table for the before/after
comparison. It also gets the `business_class` and the Turkish
`classification_reason` that decided it, because a row that vanished for
unstated reasons is a row nobody can appeal, and a `campaign_versions` entry
via `record_version`, because "the site quietly stopped showing 40 campaigns
one Tuesday" should be answerable from the database rather than from this
docstring.

Two decisions worth stating plainly
-----------------------------------
**A passing row is enriched silently.** When the rulepack says "this really is
a fare campaign" and `business_class` is still NULL, the column is filled with
ACTIVE_CAMPAIGN and *nothing else happens*: no version row, no timestamp move.
The row is served exactly as it was served yesterday, so there is no change for
a version row to describe -- writing one would put a "v1: business_class
null → ACTIVE_CAMPAIGN" entry on every surviving campaign in the table and bury
the retirements, which are the edits that actually matter, under them. (The
CHANGE alert rule reads the same version table over a 48-hour window; a
table-wide no-op diff would have become a table-wide alert flood.)

**Open alerts on a retired row are acknowledged, not deleted.** An EXPIRING
alert about a credit-card points transfer was noise, and leaving it unread in
the strip would mean retiring the campaign fixed the page but not the alert
sitting above it. Acknowledging says "this has been dealt with" and keeps the
row: the alert history is evidence of what the old pipeline was announcing, and
`campaign_alerts` has no other retirement mechanism (its FK is ON DELETE
CASCADE, i.e. deletion is reserved for a campaign that stopped existing).
Future runs of the generator skip the row on their own -- every campaign rule
there is filtered through `_publishable_promotions()`, which excludes
superseded rows -- so this only has to clear the backlog, not keep clearing it.
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.campaign_airline import NON_FARE_CLASSES, detect_business_class
from app.core.logging import get_logger
from app.models.campaign_alert import CampaignAlert
from app.models.promotion import Promotion
from app.pipeline.promo_dedup import apply_updates, record_version

logger = get_logger(__name__)


async def _acknowledge_open_alerts(
    db: AsyncSession, promotion_ids: list, *, now: datetime
) -> int:
    """Mark every unread alert about these campaigns as dealt with. Returns how
    many moved. Already-acknowledged alerts are left alone, so the count is
    "noise cleared by this run" rather than "alerts on retired rows"."""
    if not promotion_ids:
        return 0
    result = await db.execute(
        update(CampaignAlert)
        .where(
            CampaignAlert.promotion_id.in_(promotion_ids),
            CampaignAlert.acknowledged_at.is_(None),
        )
        .values(acknowledged_at=now)
    )
    return result.rowcount or 0


async def backfill_campaign_classes(
    db: AsyncSession, *, now: datetime | None = None
) -> dict:
    """Apply the business-class rulepacks to every still-published campaign row.

    Returns `{scanned, retired_by_class, enriched, unchanged,
    alerts_acknowledged}`. Idempotent by construction: a retired row is
    superseded and therefore outside the next run's scan, and an enriched row
    already carries the `business_class` the second pass would write, so a
    healthy re-run reports `retired_by_class` all zero, `enriched` 0 and every
    surviving campaign as `unchanged`.

    Scans by `superseded_at IS NULL` rather than by `business_class IS NULL`:
    the point is "what is still on the page", and a legacy row that the LLM
    once labelled ACTIVE_CAMPAIGN without these rules ever running is exactly
    the kind of row this exists to re-examine.

    Text is `title_tr` + `summary_tr` -- what the reader actually sees. `raw_text`
    is richer where it exists, but it is NULL on every legacy row (it arrived
    with the deep scanner), so reading it would make the pass depend on a
    column the rows this targets do not have.

    One commit at the end. The table is hundreds of rows, not the tens of
    thousands `backfill_risk_classification` batches through, and the
    retirement and its alert cleanup should land together or not at all.
    """
    moment = now or datetime.now(timezone.utc)

    rows = (
        await db.execute(
            select(Promotion)
            .where(Promotion.superseded_at.is_(None))
            .order_by(Promotion.detected_at.desc())
        )
    ).scalars().all()

    retired_by_class = dict.fromkeys(NON_FARE_CLASSES, 0)
    retired_ids: list = []
    enriched = unchanged = 0

    for row in rows:
        detected = detect_business_class(
            row.title_tr or "",
            row.summary_tr or "",
            sale_starts=row.sale_starts,
            sale_ends=row.sale_ends,
            travel_starts=row.travel_starts,
            travel_ends=row.travel_ends,
            discount_pct=row.discount_pct,
        )

        if detected is None:
            # A genuine fare campaign. Pure enrichment, no version row -- see
            # the module docstring.
            if row.business_class is None:
                row.business_class = "ACTIVE_CAMPAIGN"
                enriched += 1
            else:
                unchanged += 1
            continue

        business_class, reason = detected
        changed = apply_updates(
            row,
            {
                "business_class": business_class,
                "classification_reason": reason,
                "superseded_at": moment,
            },
        )
        await record_version(db, row, changed, source_url=row.url, now=moment)
        retired_by_class[business_class] += 1
        retired_ids.append(row.id)
        logger.info(
            "campaign_class_backfill_retired",
            promotion_id=str(row.id),
            airline=row.airline_code,
            business_class=business_class,
        )

    acknowledged = await _acknowledge_open_alerts(db, retired_ids, now=moment)
    await db.commit()

    summary = {
        "scanned": len(rows),
        "retired_by_class": retired_by_class,
        "enriched": enriched,
        "unchanged": unchanged,
        "alerts_acknowledged": acknowledged,
    }
    logger.info("campaign_class_backfill_complete", **summary)
    return summary
