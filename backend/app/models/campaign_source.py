"""Every page that told us about a campaign, not just the one that won.

`promotions.url` is a single column with a UNIQUE constraint on it, which makes
it the scraper's idempotency key and, unavoidably, a claim that a campaign has
one source. It does not. The same sale shows up on the airline's own campaign
page, in its newsroom, and in three trade outlets that each got a detail wrong,
and the dedup pass folds them into one row -- discarding, until now, the fact
that four independent pages agreed.

That fact is worth keeping twice over. It feeds the `corroboration` input of
the confidence score, which otherwise has to guess; and it is what makes
conflict resolution explicable, because "the official page says 40% and
Airliner News says 30%" only reads as a resolution if both sources are still on
the record. `source_tier` is the ordering that decides who wins: an airline's
own page outranks its newsroom, which outranks anyone else.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPrimaryKeyMixin


class CampaignSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "campaign_sources"
    __table_args__ = (
        # One row per URL per campaign. Re-scanning the same page updates the
        # existing row instead of inflating the corroboration count -- which is
        # the whole failure mode this table would otherwise introduce. The same
        # URL under a *different* campaign is fine: one newsroom post can
        # announce two sales.
        UniqueConstraint("promotion_id", "url", name="uq_campaign_sources_promotion_url"),
    )

    promotion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: official | newsroom | secondary. The conflict-resolution ordering, and
    #: deliberately not a Postgres enum -- see curated.py INDICATOR_KINDS for
    #: the same reasoning.
    source_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: 0..1, the per-source trust weight, mirroring sources.trust_weight for the
    #: RSS side. Carried here rather than looked up because a scraped campaign
    #: page has no row in `sources`.
    source_quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: This page's own publication date, when it has one -- a secondary outlet's
    #: article usually does, an airline campaign page usually does not.
    page_published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: sha256 of this page's extracted text, so change detection is per source:
    #: the newsroom post can go stale while the official page moves.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The sentence or two this source contributed, kept as a quotation so the
    #: drawer can show who said what. An excerpt, not a copy of the page.
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
