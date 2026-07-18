"""Shared return types for the fund-data adapters (ingest/funds/*) -- the
adapter contract the service layer programs against, mirroring ingest/base.py.

Adapters must not raise: catch and log failures, return None/[] so one dead
source never blocks the refresh of the others (see fund_service).
"""
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class HoldingRow:
    rank: int
    holding_name: str
    weight_pct: float
    ticker: str | None = None
    sector: str | None = None


@dataclass
class HoldingsSnapshot:
    as_of: date  # the issuer file's own date, not fetch time
    source: str
    source_url: str
    rows: list[HoldingRow] = field(default_factory=list)
    is_top10_only: bool = False


@dataclass
class FundProfile:
    """Fund-level metadata; every field optional because sources are flaky."""
    expense_ratio: float | None = None  # percent
    aum: float | None = None
    top_holdings: list[HoldingRow] = field(default_factory=list)
    sector_weights: list[tuple[str, float]] = field(default_factory=list)  # (label, pct)
    source: str = ""


@dataclass
class TefasPricePoint:
    as_of: datetime
    nav: float


@dataclass
class TefasInfo:
    fund_title: str  # official FONUNVAN -- overwrites the catalog placeholder
    points: list[TefasPricePoint] = field(default_factory=list)
    aum: float | None = None  # portfolio size (TRY)
    investor_count: int | None = None


@dataclass
class AllocationSlice:
    label: str
    weight_pct: float
