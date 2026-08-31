"""Human-reviewed reference data: bank FX forecasts and IATA indicators.

These two tables exist because the honest answer to "can we automate this?" was
no, for different reasons in each case.

**Bank FX forecasts.** The data is technically extractable -- ING publishes a
real HTML table, Danske a text-layer PDF in exactly the institution/horizon
shape we want. Both attach explicit "may not be reproduced or distributed
without prior written consent" notices, and ING additionally asserts database
rights and names Refinitiv as an upstream source. Everything that is free and
clear turns out to be a house model rather than a bank: TradingEconomics says
in its own page text that its numbers come from "Trading Economics global macro
models and analysts expectations", so rendering them in an `institution` column
would tell the reader a bank said something no bank said.

So rows here are narrow attributed citations, entered by a person from the named
publication, each carrying the link back to it. Horizon labels are recorded
exactly as the institution writes them -- ING publishes quarter-end (`3Q26F`),
Danske publishes `+3m`, and silently mapping either onto a tidy "3 ay" column
would be our interpolation presented as their forecast.

**IATA indicators.** IATA is the most scraping-permissive source in the whole
brief and its PDFs extract cleanly. The problem is that it publishes an industry
outlook roughly twice a year, and the numbers live in prose carrying the
qualifiers that give them meaning: "$23.0 billion in 2026, roughly half the
previously projected $41 billion, also roughly half the $45 billion estimate for
2025" is three numbers, two of them comparators. An unattended extractor will
confidently emit rows for all three and nothing downstream can tell which one
belongs in the 2026 cell.

`kind` keeps forecasts and actuals apart at the schema level. The monthly
traffic actuals ARE automated, from stable per-month slugs -- but a forecast and
a measurement are different claims about the world and must never share a card.

**Revision tracking.** A forecast row also carries the number the *previous*
edition of the same report printed for the same period. IATA halving its 2026
net-profit forecast from $41bn to $23bn between December 2025 and June 2026 is
the story; a card showing only "$23bn" prints the conclusion and throws away
the news. The three `previous_*` columns are nullable and stay NULL for actuals
(a measurement has no earlier forecast of itself) and for any forecast whose
prior edition we have not verified -- an unattributed "previous" number would
be worse than none, exactly like an invented event impact level.
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

#: Values for IataIndicator.kind. Not an enum type in Postgres: adding a third
#: kind should be a code change, not a migration with a lock on it.
INDICATOR_KINDS: tuple[str, ...] = ("forecast", "actual")


class FxForecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fx_forecasts"
    __table_args__ = (
        # The Kokpit query: one currency pair's forecasts, newest publication
        # first, optionally narrowed to a horizon.
        Index("ix_fx_forecasts_pair_published", "currency_pair", "publication_date"),
    )

    #: The institution as it names itself. Rendered verbatim next to the number,
    #: because the whole point of the row is who said it.
    institution: Mapped[str] = mapped_column(String(120))
    #: "EUR/USD", "USD/JPY" -- the pair as published, not normalised to a base.
    currency_pair: Mapped[str] = mapped_column(String(16), index=True)

    #: The institution's own horizon label: "+3m", "3Q26F", "year-end 2026".
    #: Never rewritten -- see the module docstring.
    horizon_label: Mapped[str] = mapped_column(String(40))
    #: Months ahead, for sorting and for the horizon filter. Nullable because
    #: some labels genuinely do not map to a month count, and inventing one
    #: would be the same error as rewriting the label.
    horizon_months: Mapped[int | None] = mapped_column(nullable=True)

    value: Mapped[float] = mapped_column(Float)

    #: When the institution published it. Required: a forecast without a date is
    #: unreadable -- the reader cannot tell whether it predates the news.
    publication_date: Mapped[date] = mapped_column(Date, index=True)
    #: Where the reader goes to check. Required, for the same reason.
    source_url: Mapped[str] = mapped_column(String(600))

    #: Who entered the row and when it was last checked against the source.
    #: A curated table's freshness claim is only as good as its provenance.
    entered_by: Mapped[str] = mapped_column(String(120), default="curated")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note_tr: Mapped[str | None] = mapped_column(Text, nullable=True)


class IataIndicator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "iata_indicators"
    __table_args__ = (
        Index("ix_iata_indicators_kind_period", "kind", "period_end"),
        Index("ix_iata_indicators_metric_published", "metric", "publication_date"),
    )

    #: "net_profit", "rpk_growth", "passenger_demand", "load_factor", ...
    metric: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[float] = mapped_column(Float)
    #: "USD bn", "%", "pt" -- rendered next to the value, never inferred from it.
    unit: Mapped[str] = mapped_column(String(20))

    #: forecast | actual. See INDICATOR_KINDS and the module docstring: this is
    #: the column that stops a projection being shown as a measurement.
    kind: Mapped[str] = mapped_column(String(10), index=True)

    #: The period the number describes, as a range. A full-year forecast and a
    #: single month of traffic are both expressible.
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    #: Turkish label for the period, since "2026" and "Haziran 2026" read
    #: differently and the range alone does not say which was meant.
    period_label_tr: Mapped[str] = mapped_column(String(60))

    #: World region slug, or null for a global figure.
    region: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    publication_date: Mapped[date] = mapped_column(Date, index=True)
    source_url: Mapped[str] = mapped_column(String(600))

    #: What the number means for a revenue desk, in Turkish. The owner asked for
    #: an interpretation on every IATA figure; it is written by a person for the
    #: same reason the numbers are entered by one.
    interpretation_tr: Mapped[str | None] = mapped_column(Text, nullable=True)

    entered_by: Mapped[str] = mapped_column(String(120), default="curated")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: What the *previous* edition of the same report printed for this same
    #: period, so a card can show the revision rather than only its outcome.
    #: See "Revision tracking" in the module docstring. All three are filled in
    #: together or not at all: a prior value without the edition that printed it
    #: is an unattributable number, which is what this table exists to avoid.
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
