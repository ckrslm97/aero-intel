"""What changed on a campaign, and when.

A campaign page is not a document that gets published once -- it is a surface
that gets edited. The sale window slides, the discount goes from 30% to 40%,
the route list grows, and the URL never changes. Overwriting the row in place
(which is what `promotions.url UNIQUE` makes the scraper do) is the right
storage decision and the wrong analytical one: the single fact a revenue desk
most wants is that the rival *moved*, and an in-place update erases exactly
that.

So each accepted change writes a row here instead of only mutating the parent.
Only the changed fields are stored -- a full snapshot per scan would be mostly
copies of unchanged text, and the diff is what anyone actually reads. A scan
that finds the campaign unchanged writes nothing at all and only bumps
`promotions.last_seen_at`; version numbers therefore count edits, not sightings.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPrimaryKeyMixin


class CampaignVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "campaign_versions"
    __table_args__ = (
        # Version numbers are per campaign and dense. The constraint is what
        # makes a re-run of the same scan idempotent: a second attempt to write
        # version 3 fails rather than quietly forking the history.
        UniqueConstraint("promotion_id", "version_no", name="uq_campaign_versions_promotion_no"),
    )

    promotion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), index=True
    )
    #: 1 for the first recorded edit after creation, then monotonic.
    version_no: Mapped[int] = mapped_column(Integer)

    #: {field: {"previous": ..., "new": ...}} -- both sides kept, because the
    #: interesting question about a discount that is now 40% is what it was
    #: before. This is also where a resolved conflict is logged: the losing
    #: source's value stays visible even though the official one won.
    changed_fields: Mapped[dict] = mapped_column(JSONB)

    #: Which page the change was observed on. Nullable: a merge across sources
    #: can produce a change that belongs to no single URL.
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: Only created_at, no updated_at: a version row is an immutable
    #: observation. Editing history is not a thing this table should permit.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
