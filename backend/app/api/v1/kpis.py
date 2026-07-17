"""Dashboard KPIs -- returns the latest value + recent trend per metric, in a
fixed display order. See kpi_service.py for what's real vs. derived/estimated.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.ingest.markets import fetch_history
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kpi import KpiCorroborationOut, KpiDetailOut, KpiHistoryPointOut, KpiOut

router = APIRouter(prefix="/kpis", tags=["kpis"])

# metric_key -> (display label, whether an increase is desirable)
KPI_DISPLAY: dict[str, tuple[str, bool]] = {
    "flights_airborne": ("Şu anda havada olan uçuşlar", True),
    "flights_today": ("Bugünkü uçuşlar", True),
    "passengers_ytd": ("Yolcu sayısı (2026 tahmini)", True),
    "load_factor": ("Küresel doluluk oranı", True),
    "fuel_price": ("Jet yakıtı fiyatı", False),
    "oil_price": ("Brent petrol", False),
    "fx_usd_try": ("USD/TRY", False),
    "departures": ("Uçuş kalkışları (yıllık)", True),
    "total_aviation_revenue_ytd": ("Havacılık geliri (yolcu + ek gelir)", True),
    "passenger_revenue_ytd": ("Yolcu geliri", True),
    "ancillary_revenue_ytd": ("Ek gelir", True),
    "rask": ("RASK (birim gelir)", True),
    "cask": ("CASK (birim maliyet)", False),
    "yield_per_rpk": ("Getiri (Yield)", True),
    "ask": ("ASK (kapasite)", True),
    "rpk": ("RPK (trafik)", True),
}

# metric_key -> Yahoo Finance symbol, for metrics with a real historical
# archive we can pull on demand rather than waiting for our own history to
# accumulate. "fuel_price" reuses oil's history (see get_kpi_detail).
YAHOO_HISTORY_SYMBOLS: dict[str, str] = {
    "oil_price": "BZ=F",
    "fx_usd_try": "TRY=X",
}

PERIOD_TO_TIMEDELTA: dict[str, timedelta] = {
    "1w": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}


@router.get("", response_model=list[KpiOut])
async def list_kpis(db: AsyncSession = Depends(get_db)) -> list[KpiOut]:
    repo = KpiRepository(db)
    out: list[KpiOut] = []

    for metric_key, (label, up_is_good) in KPI_DISPLAY.items():
        history = await repo.trend(metric_key, points=12)
        if not history:
            continue

        latest = history[-1]
        delta_pct = None
        if len(history) >= 2 and history[-2].value:
            delta_pct = round((latest.value - history[-2].value) / history[-2].value * 100, 2)

        out.append(
            KpiOut(
                metric_key=metric_key,
                label=label,
                value=latest.value,
                unit=latest.unit,
                delta_pct=delta_pct,
                up_is_good=up_is_good,
                trend=[h.value for h in history],
                is_estimate=latest.is_estimate,
                as_of=latest.as_of,
            )
        )

    return out


@router.get("/{metric_key}", response_model=KpiDetailOut)
async def get_kpi_detail(
    metric_key: str,
    period: str = Query("1m", pattern="^(1w|1m|3m|6m|1y)$"),
    db: AsyncSession = Depends(get_db),
) -> KpiDetailOut:
    if metric_key not in KPI_DISPLAY:
        raise HTTPException(status_code=404, detail="Unknown KPI")

    repo = KpiRepository(db)
    label, up_is_good = KPI_DISPLAY[metric_key]

    latest_rows = await repo.trend(metric_key, points=2)
    if not latest_rows:
        raise HTTPException(status_code=404, detail="No observations recorded yet for this KPI")

    latest = latest_rows[-1]
    delta_pct = None
    if len(latest_rows) == 2 and latest_rows[0].value:
        delta_pct = round((latest.value - latest_rows[0].value) / latest_rows[0].value * 100, 2)

    corroborations = [
        KpiCorroborationOut(
            source=c.source,
            source_url=c.source_url,
            value=c.value,
            as_of=c.as_of,
            diff_pct=round(abs(latest.value - c.value) / latest.value * 100, 3) if latest.value else 0.0,
        )
        for c in await repo.latest_corroborations(metric_key)
    ]

    history, history_is_external = await _load_history(db, metric_key, period)

    return KpiDetailOut(
        metric_key=metric_key,
        label=label,
        value=latest.value,
        unit=latest.unit,
        delta_pct=delta_pct,
        up_is_good=up_is_good,
        is_estimate=latest.is_estimate,
        as_of=latest.as_of,
        source=latest.source,
        source_url=latest.source_url,
        corroborations=corroborations,
        history=history,
        history_is_external=history_is_external,
        period=period,
    )


async def _load_history(
    db: AsyncSession, metric_key: str, period: str
) -> tuple[list[KpiHistoryPointOut], bool]:
    settings = get_settings()

    # fuel_price is derived from Brent crude (see kpi_service.py) -- reuse
    # oil's real historical closes and apply the same multiplier, rather than
    # waiting months for our own scheduler to accumulate a derived history.
    yahoo_symbol = YAHOO_HISTORY_SYMBOLS.get(metric_key)
    multiplier = 1.0
    if metric_key == "fuel_price":
        yahoo_symbol = YAHOO_HISTORY_SYMBOLS["oil_price"]
        multiplier = 1.18

    if yahoo_symbol:
        points = await fetch_history(settings.yahoo_finance_base_url, yahoo_symbol, period)
        if points:
            return (
                [KpiHistoryPointOut(as_of=ts, value=round(v * multiplier, 2)) for ts, v in points],
                True,
            )
        # Yahoo Finance unreachable -- fall through to our own accumulated
        # history rather than returning nothing.

    since = datetime.now(timezone.utc) - PERIOD_TO_TIMEDELTA[period]
    repo = KpiRepository(db)
    rows = await repo.history_since(metric_key, since)
    return [KpiHistoryPointOut(as_of=r.as_of, value=r.value) for r in rows], False
