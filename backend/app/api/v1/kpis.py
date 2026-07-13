"""Dashboard KPIs -- returns the latest value + recent trend per metric, in a
fixed display order. See kpi_service.py for what's real vs. derived/estimated.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kpi import KpiOut

router = APIRouter(prefix="/kpis", tags=["kpis"])

# metric_key -> (display label, whether an increase is desirable)
KPI_DISPLAY: dict[str, tuple[str, bool]] = {
    "flights_airborne": ("Flights currently airborne", True),
    "flights_today": ("Flights today", True),
    "passengers_ytd": ("Passengers this year", True),
    "load_factor": ("Global load factor", True),
    "fuel_price": ("Jet fuel price", False),
    "oil_price": ("Brent crude", False),
    "fx_usd_try": ("USD/TRY", False),
    "cancelled_flights": ("Cancelled flights today", False),
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
