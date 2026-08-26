"""A short daily Turkish commentary over Kokpit's own curated numbers -- the
FX board, the bank forecasts, the IATA indicators.

The model is only ever handed the day's already-verified figures and asked to
summarize and cite them; it is never asked to bring in a fact of its own.
market_pulse_service.py enforces this by rejecting any generated citation
whose source_url isn't one it actually supplied in the prompt, so citations
here are safe to render as clickable exactly like everywhere else in the app.

No row is written when generation fails or produces something that doesn't
validate -- see the module docstring in market_pulse_service.py. The API
then keeps serving the newest stored row, timestamped honestly, rather than a
blank card or a fabricated one.
"""
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class MarketPulse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "market_pulses"

    summary_tr: Mapped[str] = mapped_column(Text)
    #: list[{"claim": str, "source": str, "source_url": str}] -- one entry per
    #: sentence in summary_tr that cites a number, validated against the
    #: prompt's own source list before this row is ever written.
    citations: Mapped[list] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
