"""Response shapes for the /invest module (kpi.py conventions).

DISCLAIMER is a fixed string surfaced on every portfolio/analysis payload --
deliberately not LLM-generated so it can never be dropped or reworded.
"""
from datetime import date, datetime

from pydantic import BaseModel

DISCLAIMER_TR = "Bu içerik yatırım tavsiyesi değildir; yalnızca bilgilendirme amaçlıdır."


class FundOut(BaseModel):
    symbol: str
    name: str
    market: str  # "us" | "tr"
    currency: str
    issuer: str
    target_weight: float
    value: float | None  # latest close/NAV; None until first successful refresh
    as_of: datetime | None
    delta_pct: float | None  # vs previous primary observation
    trend: list[float]  # sparkline, oldest first
    verification_status: str | None  # of the latest price row
    metadata_verified: bool


class FundHistoryPointOut(BaseModel):
    as_of: datetime
    value: float


class FundHistoryOut(BaseModel):
    symbol: str
    period: str
    currency: str
    points: list[FundHistoryPointOut]


class FundCorroborationOut(BaseModel):
    source: str
    source_url: str | None
    value: float
    as_of: datetime
    diff_pct: float


class FundAnalysisOut(BaseModel):
    body_tr: str
    outlook: str  # positive | neutral | cautious
    provider: str  # openai_compat | heuristic
    analysis_date: date
    disclaimer: str = DISCLAIMER_TR


class FundDetailOut(BaseModel):
    symbol: str
    name: str
    market: str
    currency: str
    issuer: str
    target_weight: float
    expense_ratio: float | None
    aum: float | None
    aum_as_of: date | None
    metadata_source: str
    metadata_verified: bool
    value: float | None
    as_of: datetime | None
    delta_pct: float | None
    source: str | None
    source_url: str | None
    verification_status: str | None
    corroborations: list[FundCorroborationOut]
    analysis: FundAnalysisOut | None
    disclaimer: str = DISCLAIMER_TR


class FundHoldingOut(BaseModel):
    rank: int
    ticker: str | None
    holding_name: str
    weight_pct: float
    sector: str | None


class FundAllocationOut(BaseModel):
    kind: str  # asset_class | sector
    label: str
    weight_pct: float


class FundHoldingsOut(BaseModel):
    symbol: str
    as_of: date | None
    source: str | None
    verification_status: str | None
    is_top10_only: bool
    holdings: list[FundHoldingOut]
    allocations: list[FundAllocationOut]
    allocations_as_of: date | None


class PortfolioFundOut(BaseModel):
    symbol: str
    name: str
    target_weight: float
    value: float | None
    as_of: datetime | None
    return_1y_pct: float | None
    verification_status: str | None


class PortfolioOut(BaseModel):
    market: str
    funds: list[PortfolioFundOut]
    weighted_return_1y_pct: float | None  # None until every member has 1y history
    analysis: FundAnalysisOut | None
    disclaimer: str = DISCLAIMER_TR


class PortfoliosOut(BaseModel):
    us: PortfolioOut
    tr: PortfolioOut
    disclaimer: str = DISCLAIMER_TR
