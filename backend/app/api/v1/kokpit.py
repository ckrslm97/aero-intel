"""Kokpit: the FX board, curated bank/IATA forecasts, and the daily Market
Pulse. See app/models/curated.py and app/services/market_pulse_service.py for
why these are hand-curated rather than scraped.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, CURATED, FX, public_cache
from app.core.db import get_db
from app.ingest.historical_seed import PUBLISHED_AT as IATA_PUBLISHED_AT
from app.ingest.historical_seed import SOURCE as IATA_SOURCE
from app.ingest.historical_seed import SOURCE_URL as IATA_SOURCE_URL
from app.ingest.historical_seed import YEARS as IATA_YEARS
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.schemas.kokpit import (
    AnnualPointOut,
    AnnualSeriesBoardOut,
    AnnualSeriesOut,
    CockpitSignalsOut,
    FxForecastOut,
    IataIndicatorOut,
    KokpitFxBoardOut,
    KokpitFxPairOut,
    KokpitFxPegOut,
    MarketPulseOut,
)
from app.services.cockpit_signals_service import cockpit_signals
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
                day_delta_pct=_delta_pct(latest.value, day_ago.value if day_ago else None),
                week_delta_pct=_delta_pct(latest.value, week_ago.value if week_ago else None),
                month_delta_pct=_delta_pct(latest.value, month_ago.value if month_ago else None),
                sparkline=[row.value for row in sparkline_rows],
                as_of=latest.as_of,
                source=latest.source,
                source_url=latest.source_url,
                frequency_label=FX_FREQUENCY_LABEL,
            )
        )

    return KokpitFxBoardOut(pairs=pairs, peg=SAR_PEG)


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
    return [FxForecastOut.model_validate(row) for row in rows]


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

# IATA published the June 2026 outlook with the current year as a forecast and
# the year before it as an estimate (see historical_seed.py's own note). Derived
# from PUBLISHED_AT rather than hardcoded, so re-seeding from a later report
# moves the dashed tail of the chart with it.
FORECAST_YEAR = IATA_PUBLISHED_AT.year
ESTIMATE_YEAR = FORECAST_YEAR - 1

ANNUAL_SCOPE_TR = "sektör geneli · yıllık · IATA Küresel Görünüm (Haziran 2026)"


def _year_kind(year: int) -> str:
    if year >= FORECAST_YEAR:
        return "forecast"
    if year == ESTIMATE_YEAR:
        return "estimate"
    return "actual"


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
