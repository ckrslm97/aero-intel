"""Airline campaigns/promotions as first-class rows.

Why its own table rather than a sixth `aviation_events.event_type`: a campaign
is not an event. `aviation_events` has no airline column at all -- it is keyed
on city/country, because a trade show happens *somewhere*, while a campaign is
run *by someone*. The calendar's five event types are also a closed set mapped
one-to-one onto the five --chart-* dataviz tokens; a sixth type would have no
colour left to wear. So campaigns get their own table and their own visual
layer (carrier brand hex, overlay ribbons), and the calendar renders both.

Every date column is nullable on purpose. Campaigns reach us two ways -- an
official campaign page (dated, precise) and press coverage (vague: "this
summer", "through the end of the month", or no window at all). Forcing a date
would mean inventing one, and an invented sale window is indistinguishable
from a measured one once it is drawn as a bar. The frontend renders each
missing field honestly instead: an open-ended bar fades out, a campaign with
no start date at all becomes a point marker at `detected_at` rather than a bar.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Promotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "promotions"

    # IATA code matching entities.code and frontend nav.ts airlineTabs -- this
    # is what binds a row to its brand colour and logo on the timeline.
    airline_code: Mapped[str] = mapped_column(String(6), index=True)
    airline_name: Mapped[str] = mapped_column(String(120))

    title_tr: Mapped[str] = mapped_column(String(300))
    summary_tr: Mapped[str] = mapped_column(Text, default="")

    # "%40'a varan" -> 40. None when the source states no rate (a "9 Euro'dan
    # başlayan" fare campaign has no percentage), and the drawer says so rather
    # than rendering an empty badge.
    discount_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Comma-separated world-region slugs (app/taxonomy.py COUNTRY_TO_REGION
    # values) and/or plain city names, mixed. Deliberately not JSON: the only
    # consumers split on comma and render chips, and a JSON column would buy
    # nothing but a migration's worth of ceremony.
    markets: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: The structured form, for the cascading Region -> Country -> City filter:
    #: {"regions": [...], "countries": [...], "cities": [...]}. The comment above
    #: is right that JSON bought nothing while the only consumer split on commas
    #: and rendered chips -- a cascading filter is the consumer that changes
    #: that. Added alongside rather than replacing `markets`, so the old writer
    #: keeps working until the campaign agent replaces it.
    markets_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # When tickets can be BOUGHT. This is the window the timeline draws and the
    # calendar ribbons, because it is the one a revenue desk has to react to.
    sale_starts: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    sale_ends: Mapped[date | None] = mapped_column(Date, nullable=True)
    # When the discounted ticket can be FLOWN -- usually much later and much
    # wider than the sale window, and what tells you which season is at risk.
    travel_starts: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_ends: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Idempotency key, same convention as aviation_events.url: the campaign
    # page for a scraped row, the article URL for an article-derived one.
    url: Mapped[str] = mapped_column(String(500), unique=True)
    source_name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    #: The news event this campaign was extracted from, when it came from an
    #: article rather than a scraped campaign page.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="SET NULL"), nullable=True
    )

    # --- validation and confidence ------------------------------------------
    #
    # 55% of what this table published was not a campaign: Etihad Rail tickets,
    # a Eurostar review, a Marriott points guide, an LNG pricing article, an
    # IAG Cargo revenue *decline* read as a 9% discount, and three rows whose
    # titles literally began "[Expired]". 92% had no sale date at all. The
    # columns below are how a row now has to earn its place on the page.

    #: valid | incomplete | rejected. Set by the campaign agent's validate()
    #: before anything is written, so an unvalidated row cannot exist.
    validation_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Read endpoints serve high and medium. A campaign missing its sale window
    #: is capped at medium by pipeline/confidence.py and, if it is missing more
    #: than half its required fields, at low -- which means invisible.
    confidence_band: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    confidence_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Soft delete. The 124 mis-extracted rows are marked rather than destroyed,
    #: so the before/after comparison stays checkable.
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

        # When WE first saw it -- not when the airline launched it. This is what
    # drives the "Yeni" badge and the 48h banner, and it is the only freshness
    # claim we can actually stand behind: an airline's own page carries no
    # publication timestamp, and a news report's date is the reporter's, not
    # the campaign's. Indexed because every list query orders or filters on it.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# How recently-detected a campaign has to be to still count as "new" on the
# timeline. Shared by the API and referenced by the frontend banner copy.
NEW_WINDOW_HOURS = 48
