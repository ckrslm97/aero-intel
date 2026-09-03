"""Kokpit: the FX board, curated bank/IATA forecasts, and the daily Market
Pulse. See app/models/curated.py and app/services/market_pulse_service.py for
why these are hand-curated rather than scraped.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, CURATED, FX, public_cache
from app.core.db import get_db

# The one resolver for "when is this forecast for" -- the FX table, the chart
# and the repository's `only_upcoming` filter all read this same answer.
from app.forecast_horizon import QUARTER_MIDPOINTS, forecast_target_date  # noqa: F401
from app.ingest.historical_seed import SOURCE as IATA_SOURCE
from app.ingest.historical_seed import SOURCE_URL as IATA_SOURCE_URL
from app.ingest.historical_seed import YEARS as IATA_YEARS

# "Which year is a forecast" is the seed report's own fact, so it is imported
# rather than re-derived here: /kpis labels its periods with the same helper,
# and two copies of the rule would be two chances for a KPI card and the chart
# beside it to disagree about 2026.
from app.ingest.historical_seed import year_kind as _year_kind
from app.models.kpi import KPI
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.schemas.kokpit import (
    AnnualPointOut,
    AnnualSeriesBoardOut,
    AnnualSeriesOut,
    CockpitSignalsOut,
    EnergyBoardOut,
    EnergyMetricOut,
    FxForecastOut,
    IataIndicatorOut,
    KokpitFxBoardOut,
    KokpitFxPairOut,
    KokpitFxPegOut,
    MarketPulseOut,
)
from app.services.cockpit_signals_service import cockpit_signals
from app.services.energy_service import (
    PERCENTILE_METHOD_TR,
    VOLATILITY_METHOD_TR,
    energy_metrics,
)
from app.services.kpi_service import FX_PAIR_LABELS, LIVE_FX_PAIRS

router = APIRouter(prefix="/kokpit", tags=["kokpit"])

# Sourced from the Saudi Central Bank's own statement of policy: the riyal has
# been pegged to the US dollar at this exact rate since June 1986. There is no
# "current rate" to fetch -- a provider's daily series for this pair is either
# a rounding artefact or synthetic noise around a number that does not move,
# which is why it gets a static badge instead of a row in the live board.
SAR_PEG = KokpitFxPegOut(
    currency_pair="USD/SAR",
    value=3.75,
    label="Sabit · 3,75 (SAMA)",
    source="Saudi Central Bank (SAMA)",
    source_url="https://www.sama.gov.sa/en-US/EconomicReports/Pages/report.aspx",
)

# What the 15-minute refresh job (jobs-kpis.yml) actually delivers -- shown
# next to each pair so "günlük" doesn't imply a frequency the data doesn't have.
FX_FREQUENCY_LABEL = "~15 dakikada bir"


def _delta_pct(latest: float, prior: float | None) -> float | None:
    if prior is None or prior == 0:
        return None
    return round((latest - prior) / prior * 100, 2)


def _window_delta(latest: KPI, prior: KPI | None) -> float | None:
    """Percent change across a window, or None when the window never closed.

    `KpiRepository.closest_before` answers with the newest row at or before the
    cutoff. When the 15-minute cron has been down long enough that the NEWEST
    reading is itself older than the cutoff, that row IS `latest`, and the old
    code happily divided a value by itself and published "0.0". On a board two
    days stale that printed a confident "%0,0" in the 1G column of all eight
    pairs -- eight assertions that the lira had not moved in a day, when the
    truth was that nobody had measured it for two. Worse, the same row's 1H
    column correctly said "—", so one row made two contradictory claims.

    A window that did not close carries no change. The UI already renders None
    as "—" with "yeterli geçmiş yok", which is exactly the right sentence.
    """
    if prior is None or prior.as_of >= latest.as_of:
        return None
    return _delta_pct(latest.value, prior.value)


@router.get("/fx", response_model=KokpitFxBoardOut)
async def get_fx_board(response: Response, db: AsyncSession = Depends(get_db)) -> KokpitFxBoardOut:
    public_cache(response, FX)
    repo = KpiRepository(db)
    now = datetime.now(timezone.utc)

    pairs: list[KokpitFxPairOut] = []
    for metric_key, *_rest in LIVE_FX_PAIRS:
        latest = await repo.latest(metric_key)
        if latest is None:
            continue
        sparkline_rows = await repo.trend(metric_key, points=48)
        day_ago = await repo.closest_before(metric_key, now - timedelta(days=1))
        week_ago = await repo.closest_before(metric_key, now - timedelta(days=7))
        month_ago = await repo.closest_before(metric_key, now - timedelta(days=30))

        pairs.append(
            KokpitFxPairOut(
                currency_pair=FX_PAIR_LABELS.get(metric_key, metric_key),
                value=latest.value,
                unit=latest.unit,
                day_delta_pct=_window_delta(latest, day_ago),
                week_delta_pct=_window_delta(latest, week_ago),
                month_delta_pct=_window_delta(latest, month_ago),
                sparkline=[row.value for row in sparkline_rows],
                as_of=latest.as_of,
                source=latest.source,
                source_url=latest.source_url,
                frequency_label=FX_FREQUENCY_LABEL,
            )
        )

    return KokpitFxBoardOut(pairs=pairs, peg=SAR_PEG)


# --- Forecast target dates ------------------------------------------------
#
# The mapping itself, and the reasoning for every rung of it, now lives in
# app/forecast_horizon.py: the repository's `only_upcoming` filter asks the
# same question ("is this forecast still about the future?") and used to answer
# it with a weaker copy that could only date a row carrying `horizon_months`.
# One question, one implementation.


def _with_target_date(row) -> FxForecastOut:
    out = FxForecastOut.model_validate(row)
    target, basis = forecast_target_date(
        horizon_months=row.horizon_months,
        horizon_label=row.horizon_label,
        publication_date=row.publication_date,
    )
    return out.model_copy(update={"target_date": target, "target_date_basis_tr": basis})


@router.get("/fx-forecasts", response_model=list[FxForecastOut])
async def get_fx_forecasts(
    response: Response,
    pair: str | None = Query(None, alias="pair"),
    horizon_months: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[FxForecastOut]:
    public_cache(response, CURATED)
    repo = CuratedRepository(db)
    rows = await repo.fx_forecasts(currency_pair=pair, horizon_months=horizon_months)
    return [_with_target_date(row) for row in rows]


@router.get("/energy", response_model=EnergyBoardOut)
async def get_energy_board(response: Response) -> EnergyBoardOut:
    """Brent, WTI, Henry Hub gas and the derived jet-fuel row, each with the
    changes/percentile/volatility computed from its own daily closes.

    Takes no database session: every figure here is arithmetic over Yahoo's
    published history, and reading it from the same place the KPI detail page
    reads it keeps the two from disagreeing.
    """
    # FX rather than CURATED: these move with the market, on the same cadence
    # as the FX board they sit beside.
    public_cache(response, FX)
    metrics = [
        EnergyMetricOut(
            metric_key=row.metric_key,
            label_tr=row.label_tr,
            unit=row.unit,
            value=row.indicators.value,
            as_of=row.indicators.as_of,
            day_change_pct=row.indicators.day_change_pct,
            week_change_pct=row.indicators.week_change_pct,
            month_change_pct=row.indicators.month_change_pct,
            ytd_change_pct=row.indicators.ytd_change_pct,
            percentile_1y=row.indicators.percentile_1y,
            volatility_30d_pct=row.indicators.volatility_30d_pct,
            sparkline=row.indicators.sparkline,
            source=row.source,
            source_url=row.source_url,
            href=row.href,
            is_estimate=row.is_estimate,
            note_tr=row.note_tr,
        )
        for row in await energy_metrics()
    ]
    return EnergyBoardOut(
        metrics=metrics,
        volatility_method_tr=VOLATILITY_METHOD_TR,
        percentile_method_tr=PERCENTILE_METHOD_TR,
    )


@router.get("/iata", response_model=list[IataIndicatorOut])
async def get_iata_indicators(
    response: Response,
    kind: str | None = Query(None, pattern="^(forecast|actual)$"),
    region: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[IataIndicatorOut]:
    public_cache(response, CURATED)
    repo = CuratedRepository(db)
    rows = await repo.iata_indicators(kind=kind, region=region)
    return [IataIndicatorOut.model_validate(row) for row in rows]


@router.get("/pulse", response_model=MarketPulseOut)
async def get_market_pulse(response: Response, db: AsyncSession = Depends(get_db)) -> MarketPulseOut:
    repo = MarketPulseRepository(db)
    pulse = await repo.latest()
    if pulse is None:
        raise HTTPException(status_code=404, detail="No market pulse generated yet")
    public_cache(response, CURATED)
    return MarketPulseOut.model_validate(pulse, from_attributes=True)


@router.get("/signals", response_model=CockpitSignalsOut)
async def get_cockpit_signals(
    response: Response, db: AsyncSession = Depends(get_db)
) -> CockpitSignalsOut:
    """The four Sinyal Panosu tiles. Deterministic, no LLM -- see
    app/services/cockpit_signals_service.py for the thresholds and for why this
    is four separate signals rather than one composite score."""
    # AGGREGATES: the drivers behind these tiles are the risk rollup, the
    # campaign table and two market metrics, none of which move faster than the
    # crons that write them.
    public_cache(response, AGGREGATES)
    return CockpitSignalsOut(
        signals=await cockpit_signals(db), generated_at=datetime.now(timezone.utc)
    )


# --- IATA annual series ---------------------------------------------------

# The industry series Kokpit's "IATA Sektör Görünümü" plots, in display order,
# with the short label a chart legend or a strip cell can actually fit.
# `KPI_DISPLAY`'s labels ("RPK (trafik)", "Havacılık geliri (yolcu + ek gelir)")
# are written for a full-width card and are far too long for either.
#
# Every one of these is an IATA GLOBAL INDUSTRY figure, annual, 2019-2026 -- not
# monthly, not THY's own. app/ingest/historical_seed.py is the single
# transcription behind all of them, and AnnualSeriesBoardOut.scope_tr carries
# that caveat into the payload so no surface can print these as company numbers.
ANNUAL_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("passengers_ytd", "Yolcu", True),
    ("rpk", "RPK", True),
    ("ask", "ASK", True),
    ("load_factor", "Doluluk", True),
    ("yield_per_rpk", "Getiri", True),
    ("rask", "RASK", True),
    ("cask", "CASK", False),
    ("total_aviation_revenue_ytd", "Gelir (yolcu+ek)", True),
    ("passenger_revenue_ytd", "Yolcu geliri", True),
    ("ancillary_revenue_ytd", "Ek gelir", True),
)

ANNUAL_SCOPE_TR = "sektör geneli · yıllık · IATA Küresel Görünüm (Haziran 2026)"


@router.get("/annual-series", response_model=AnnualSeriesBoardOut)
async def get_annual_series(
    response: Response, db: AsyncSession = Depends(get_db)
) -> AnnualSeriesBoardOut:
    """The 2019-2026 IATA industry series behind the sector chart and KPI strip.

    Reuses `KpiRepository.trends_for` rather than adding a query: these metrics
    are published estimates, so `_record_if_changed` (kpi_service.py) means the
    stored primary rows for each of them ARE the annual points -- one per year,
    at that year's own timestamp. More rows than years are asked for anyway,
    and the newest row per year wins, so a mid-year IATA revision adds a point
    to 2026 instead of silently pushing 2019 off the front of the chart.
    """
    public_cache(response, CURATED)
    repo = KpiRepository(db)
    keys = [key for key, _, _ in ANNUAL_METRICS]
    trends = await repo.trends_for(keys, points=len(IATA_YEARS) * 2)

    series: list[AnnualSeriesOut] = []
    for metric_key, label_tr, up_is_good in ANNUAL_METRICS:
        rows = trends.get(metric_key) or []
        if not rows:
            continue
        # rows arrive oldest-first, so a later row for the same year overwrites
        # an earlier one -- "newest wins", stated as a dict insert.
        by_year = {row.as_of.year: row for row in rows}
        points = [
            AnnualPointOut(year=year, value=row.value, kind=_year_kind(year))
            for year, row in sorted(by_year.items())
        ]
        series.append(
            AnnualSeriesOut(
                metric_key=metric_key,
                label_tr=label_tr,
                unit=rows[-1].unit,
                up_is_good=up_is_good,
                points=points,
            )
        )

    return AnnualSeriesBoardOut(
        series=series,
        source=IATA_SOURCE,
        source_url=IATA_SOURCE_URL,
        scope_tr=ANNUAL_SCOPE_TR,
    )
