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


class CockpitSignalOut(BaseModel):
    """One tile on Kokpit's "Sinyal Panosu".

    Deliberately NOT a score. Each tile states one real driver, the threshold
    band that driver falls into, and where the number came from -- see
    app/services/cockpit_signals_service.py for why a blended 0-100 "health
    score" was rejected.
    """

    #: fx | fuel | risk | competitor
    key: str
    label_tr: str
    #: good | warning | critical -- maps onto the frontend's status tokens.
    level: str
    level_label_tr: str
    #: The one number driving the level, already formatted for display so the
    #: tile and the sentence beneath it can never round differently.
    value_label: str
    reason_tr: str
    #: How the level was computed, verbatim. Rendered as the tile's ⓘ note.
    method_tr: str
    source: str
    source_url: str | None
    #: In-app destination for "detay" -- None where the tile has no deeper page.
    href: str | None
    #: When the driving observation was taken. None where the driver is a
    #: rolling window rather than a point reading.
    as_of: datetime | None


class CockpitSignalsOut(BaseModel):
    signals: list[CockpitSignalOut]
    generated_at: datetime


class AnnualPointOut(BaseModel):
    year: int
    value: float
    #: actual | estimate | forecast. IATA's June 2026 outlook publishes 2026 as
    #: a forecast and 2025 as an estimate; everything earlier is a reported
    #: actual. Kept per point so the chart can draw the tail dashed rather than
    #: the frontend re-deriving which years are not yet history.
    kind: str


class AnnualSeriesOut(BaseModel):
    metric_key: str
    #: Short label for a chart legend / strip cell, e.g. "RPK", "Doluluk".
    label_tr: str
    unit: str
    up_is_good: bool
    points: list[AnnualPointOut]


class AnnualSeriesBoardOut(BaseModel):
    series: list[AnnualSeriesOut]
    #: "IATA Küresel Görünüm (Haziran 2026)" -- one attribution for the whole
    #: board, because every series comes from the same single document.
    source: str
    source_url: str
    #: "sektör geneli · yıllık" -- the scope caveat the UI must print next to
    #: any of these numbers, so no surface can show them as TK's own.
    scope_tr: str
