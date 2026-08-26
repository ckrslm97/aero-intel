"""Kokpit: the FX board, curated bank/IATA forecasts, and the daily Market
Pulse. See app/models/curated.py and app/services/market_pulse_service.py for
why these are hand-curated rather than scraped.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import CURATED, FX, public_cache
from app.core.db import get_db
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.schemas.kokpit import (
    FxForecastOut,
    IataIndicatorOut,
    KokpitFxBoardOut,
    KokpitFxPairOut,
    KokpitFxPegOut,
    MarketPulseOut,
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
