"""What a revenue desk should be told about a campaign, once.

The rest of the campaign surface answers "what is true right now" -- the table,
the timeline, the status function all re-derive themselves from the row and
today's date every time they are read. An alert is the opposite kind of object:
it is a *notification*, and a notification that fires twice is worse than one
that does not fire at all. Nobody re-reads a list where the same "QR flaş
indirim başladı" line appears four times because the cron ran four times.

That is the whole reason this table exists rather than the alert list being a
query. A query cannot remember that it already said something.

`dedupe_key` is what carries that memory, and it is deliberately the only
UNIQUE constraint here. Its shape is `{promotion_id}:{alert_type}:{bucket}`,
where the bucket is whatever makes *one real event* distinct:

    NEW              the day we first saw the campaign
    CHANGE           the version number of the edit
    EXPIRING         the sale_ends date the warning is about
    EXPIRED          the sale_ends date that has now passed
    LOW_CONFIDENCE   the day the unreviewed row first appeared

None of those buckets is "the time the job ran", which is the point. GitHub's
scheduler is measured 2-2.75 hours late on this repo (see
services/delivery_window.py), the generator is called from two different
workflows on purpose, and a manual dispatch can add a third run in the same
hour. Every one of those paths recomputes the identical key and the identical
row, so the second and third writes are no-ops rather than duplicates -- and a
run that is *skipped* entirely still catches the alert on the next pass,
because the bucket is a property of the campaign, not of the clock.

`acknowledged_at` is nullable and never set by the generator: an alert is
unread until a person marks it read. The read endpoint serves only the
unacknowledged ones, so acknowledging is how the strip empties. v1 ships no
acknowledge UI (see the plan's out-of-scope list) -- the column exists now
because adding it later would mean a second migration for a boolean nobody
disputes the shape of.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPrimaryKeyMixin

#: Why we are telling you. Validated in the app layer, not by a Postgres enum,
#: for the same reason as every other closed set in this codebase: growing the
#: list should be a code change, not a migration holding a lock.
ALERT_TYPES: tuple[str, ...] = (
    "NEW",
    "CHANGE",
    "EXPIRING",
    "EXPIRED",
    "LOW_CONFIDENCE",
)

#: How loudly. Ordered most-urgent first -- the read endpoint sorts on this
#: order, so the tuple is the display contract as well as the value set.
ALERT_PRIORITIES: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "INFO")

#: Turkish labels for the mail and the frontend strip.
ALERT_PRIORITY_LABELS_TR: dict[str, str] = {
    "CRITICAL": "Kritik",
    "HIGH": "Yüksek",
    "MEDIUM": "Orta",
    "INFO": "Bilgi",
}

ALERT_TYPE_LABELS_TR: dict[str, str] = {
    "NEW": "Yeni kampanya",
    "CHANGE": "Kampanya değişikliği",
    "EXPIRING": "Bitmek üzere",
    "EXPIRED": "Sona erdi",
    "LOW_CONFIDENCE": "İnceleme gerekiyor",
}


class CampaignAlert(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "campaign_alerts"

    #: CASCADE rather than SET NULL: an alert about a campaign that no longer
    #: exists is an orphan nobody can act on. Soft-deleted campaigns
    #: (`superseded_at`) keep their alerts, because that row is still readable.
    promotion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), index=True
    )

    alert_type: Mapped[str] = mapped_column(String(20))
    #: Indexed because the only ordering this table is ever read in starts here.
    priority: Mapped[str] = mapped_column(String(10), index=True)

    #: The whole message, pre-composed in Turkish. Rendering it at read time
    #: from detail_json would mean the mail, the API and the frontend each
    #: reinventing the same sentence -- and disagreeing about it.
    title_tr: Mapped[str] = mapped_column(String(300))

    #: The structured payload behind the sentence: carrier, url, campaign_type,
    #: discount, the date window, which priority boosts fired, and for a CHANGE
    #: the field-level diff. Nullable so a future alert type that genuinely has
    #: no detail is not forced to write `{}`.
    detail_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Indexed: "the last 24 hours" is the daily mail's query and the strip's.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: `{promotion_id}:{alert_type}:{bucket}` -- see the module docstring. 120
    #: characters is a UUID (36) plus the longest type (14) plus a generous
    #: bucket, with room left over; a key that would exceed it is a bug in the
    #: bucket, not a reason to widen the column.
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True)
