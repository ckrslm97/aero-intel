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
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
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

    # When WE first saw it -- not when the airline launched it. This is what
    # drives the "Yeni" badge and the 48h banner, and it is the only freshness
    # claim we can actually stand behind: an airline's own page carries no
    # publication timestamp, and a news report's date is the reporter's, not
    # the campaign's. Indexed because every list query orders or filters on it.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# How recently-detected a campaign has to be to still count as "new" on the
# timeline. Shared by the API and referenced by the frontend banner copy.
NEW_WINDOW_HOURS = 48
