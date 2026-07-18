"""Structured aviation-industry calendar entries (airshows, conferences,
demand-driving holidays, sports, festivals).

Separate from articles on purpose: the Gazete's Etkinlik tab renders events as
news-style cards, but a *calendar* page needs real start/end dates to group by
month and filter by region -- dates buried inside a headline string can't do
that. Both are written by the same seed (app/ingest/events_seed.py), so they
never drift apart.
"""
from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

EVENT_TYPES = ("airshow", "conference", "sports", "holiday", "festival")


class AviationEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "aviation_events"

    name: Mapped[str] = mapped_column(String(300))
    starts: Mapped[date] = mapped_column(Date, index=True)
    ends: Mapped[date] = mapped_column(Date)
    city: Mapped[str] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # World-region slug from app/taxonomy.py COUNTRY_TO_REGION's value set;
    # None = global scope (shows under "Genel").
    region: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    # Official/organiser URL -- also the idempotency key for seeding.
    url: Mapped[str] = mapped_column(String(500), unique=True)
    summary_tr: Mapped[str] = mapped_column(Text, default="")
    event_type: Mapped[str] = mapped_column(String(20), index=True)  # see EVENT_TYPES
