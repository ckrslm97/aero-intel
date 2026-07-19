"""Passenger reviews about Turkish Airlines collected from public web sources
(Skytrax, app stores, Reddit, forums) for the BİZ page.

Collection is agent-driven and curated into app/ingest/tk_reviews_seed.py --
there is no scheduled scraper on purpose: review sites are fragile to scrape
and mostly disallow it, so refreshes happen as explicit curation passes.
Excerpts are kept to one or two sentences with a source link (quotation, not
reproduction).
"""
from datetime import date

from sqlalchemy import JSON, Date, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# Fixed theme vocabulary (slug -> Turkish label). The seed data tags each
# review with 1-3 of these; the BİZ page aggregates on the slugs and displays
# the labels, so both sides must draw from this dict.
REVIEW_THEMES: dict[str, str] = {
    "cabin_crew": "Kabin Ekibi",
    "seat_comfort": "Koltuk & Konfor",
    "food": "İkram",
    "delay": "Gecikme & Operasyon",
    "baggage": "Bagaj",
    "refund_service": "İade & Müşteri Hizmetleri",
    "miles_smiles": "Miles&Smiles",
    "ist_transfer": "İstanbul Transfer",
    "value": "Fiyat/Değer",
    "entertainment": "Uçak İçi Eğlence",
}

REVIEW_SENTIMENTS = ("positive", "neutral", "negative")


class TkReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tk_reviews"

    source_name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(600))
    # sha256 of url+excerpt: several reviews can share one listing URL
    # (paginated Skytrax pages, a Reddit thread), so the URL alone cannot be
    # the seeding idempotency key.
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Normalized to a 0-10 scale regardless of the source site's own scale;
    # None for forum posts that carry no score.
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    route: Mapped[str | None] = mapped_column(String(60), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text)
    excerpt_tr: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str] = mapped_column(String(10), index=True)  # see REVIEW_SENTIMENTS
    themes: Mapped[list] = mapped_column(JSON, default=list)  # REVIEW_THEMES slugs
