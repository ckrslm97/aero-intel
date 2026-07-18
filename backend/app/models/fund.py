"""Fund/ETF tables behind the /invest module.

Deliberately separate from the aviation KPI tables: the module has its own
catalog (funds_catalog.py), its own refresh job, and its own verification
vocabulary. Every price and holding row records where it came from and whether
a second source corroborated it -- the UI renders that status as a badge and
never presents unverified data as verified.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# verification_status values (kept as strings, mirroring taxonomy-style constants)
VERIFIED = "verified"  # two independent sources agreed within tolerance
OFFICIAL_SINGLE_SOURCE = "official_single_source"  # TEFAS: authoritative, no independent mirror exists
SINGLE_SOURCE = "single_source"  # cross-check unavailable; honestly unconfirmed
DISCREPANCY = "discrepancy"  # sources disagreed beyond tolerance; surfaced, not hidden


class Fund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "funds"

    symbol: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    market: Mapped[str] = mapped_column(String(5))  # "us" | "tr"
    name: Mapped[str] = mapped_column(String(300))
    currency: Mapped[str] = mapped_column(String(5))
    issuer: Mapped[str] = mapped_column(String(120), default="")
    target_weight: Mapped[float] = mapped_column(Float)  # user's example allocation
    expense_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # percent
    aum: Mapped[float | None] = mapped_column(Float, nullable=True)  # fund currency
    aum_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_source: Mapped[str] = mapped_column(String(100), default="")
    # True only when two sources agreed on the metadata (or it came from the
    # authoritative issuer/regulator record).
    metadata_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class FundPrice(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fund_prices"
    __table_args__ = (Index("ix_fund_prices_fund_as_of", "fund_id", "as_of"),)

    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id", ondelete="CASCADE"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[float] = mapped_column(Float)  # close (ETF) or NAV (TEFAS)
    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Same N-source corroboration pattern as KPI.is_primary: the primary row
    # drives the chart; secondary rows are cross-checks kept for the detail page.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(30), default=SINGLE_SOURCE)


class FundHolding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fund_holdings"
    __table_args__ = (Index("ix_fund_holdings_fund_as_of", "fund_id", "as_of"),)

    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(Date)  # the issuer file's own date
    rank: Mapped[int] = mapped_column(Integer)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    holding_name: Mapped[str] = mapped_column(String(300))
    weight_pct: Mapped[float] = mapped_column(Float)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(100))
    verification_status: Mapped[str] = mapped_column(String(30), default=SINGLE_SOURCE)
    # True when only a top-10 list was available (e.g. VHT via Yahoo fallback),
    # so the UI can say "top 10" instead of implying full coverage.
    is_top10_only: Mapped[bool] = mapped_column(Boolean, default=False)


class FundAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fund_allocations"
    __table_args__ = (Index("ix_fund_allocations_fund_as_of", "fund_id", "as_of"),)

    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # "asset_class" (TEFAS) | "sector" (rolled up from holdings)
    label: Mapped[str] = mapped_column(String(120))
    weight_pct: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(100))


class FundAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fund_analyses"
    __table_args__ = (
        UniqueConstraint("scope", "fund_id", "analysis_date", name="uq_fund_analyses_scope_fund_date"),
    )

    scope: Mapped[str] = mapped_column(String(20))  # "fund" | "portfolio_us" | "portfolio_tr"
    fund_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funds.id", ondelete="CASCADE"), nullable=True
    )
    analysis_date: Mapped[date] = mapped_column(Date)
    body_tr: Mapped[str] = mapped_column(Text)
    outlook: Mapped[str] = mapped_column(String(20), default="neutral")  # positive | neutral | cautious
    # Which pipeline wrote it ("openai_compat" | "heuristic"), rendered in the UI
    # exactly like InsightDigest.provider so template text is never passed off as AI analysis.
    provider: Mapped[str] = mapped_column(String(30), default="heuristic")
    # Hash of the stats fed to the LLM -- regeneration is skipped when the
    # underlying data hasn't changed (protects the daily token budget).
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="")
