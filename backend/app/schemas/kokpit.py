from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class KokpitFxPairOut(BaseModel):
    currency_pair: str
    value: float
    unit: str
    # None where there is not yet an observation far enough back -- an honest
    # "not enough history" rather than a fabricated 0%. Fills in on its own as
    # the 15-minute refresh job accumulates history (see kpi_service.py).
    day_delta_pct: float | None
    week_delta_pct: float | None
    month_delta_pct: float | None
    sparkline: list[float]
    as_of: datetime
    source: str
    source_url: str | None
    frequency_label: str


class KokpitFxPegOut(BaseModel):
    currency_pair: str
    value: float
    label: str
    source: str
    source_url: str


class KokpitFxBoardOut(BaseModel):
    pairs: list[KokpitFxPairOut]
    peg: KokpitFxPegOut


class FxForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    institution: str
    currency_pair: str
    horizon_label: str
    horizon_months: int | None
    value: float
    publication_date: date
    source_url: str
    note_tr: str | None


class IataIndicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric: str
    kind: str
    value: float
    unit: str
    period_start: date
    period_end: date
    period_label_tr: str
    region: str | None
    publication_date: date
    source_url: str
    interpretation_tr: str | None


class MarketPulseCitationOut(BaseModel):
    claim: str
    source: str
    source_url: str


class MarketPulseOut(BaseModel):
    summary_tr: str
    citations: list[MarketPulseCitationOut]
    generated_at: datetime
