from datetime import datetime

from pydantic import BaseModel


class KpiOut(BaseModel):
    metric_key: str
    label: str
    value: float
    unit: str
    delta_pct: float | None  # vs the previous observation (unchanged semantics)
    up_is_good: bool
    trend: list[float]
    is_estimate: bool
    as_of: datetime
    # Last-year (2025) comparison: the metric's 2025 value where one exists
    # (IATA's 2025 column, or the market price a year ago), else None.
    ly_value: float | None
    ly_delta_pct: float | None  # latest value vs ly_value, rounded to 2dp
    comparison_label: str  # "2025 (LY)'e göre" when LY exists, else "önceki ölçüme göre"


class KpiHistoryPointOut(BaseModel):
    as_of: datetime
    value: float


class KpiCorroborationOut(BaseModel):
    source: str
    source_url: str | None
    value: float
    as_of: datetime
    diff_pct: float


class KpiDetailOut(BaseModel):
    metric_key: str
    label: str
    value: float
    unit: str
    delta_pct: float | None
    up_is_good: bool
    is_estimate: bool
    as_of: datetime
    source: str
    source_url: str | None
    corroborations: list[KpiCorroborationOut]
    history: list[KpiHistoryPointOut]
    # True when `history` came from the source's own historical archive
    # (Yahoo Finance, for oil/FX); False when it's our own accumulated
    # observations, which will be sparse until the scheduler has run a while.
    history_is_external: bool
    period: str
