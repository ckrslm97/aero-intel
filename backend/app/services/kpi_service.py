"""Refreshes dashboard KPIs: real values from OpenSky/Yahoo Finance where free
data exists, transparently-derived or static estimates otherwise. Every call
inserts a new timestamped row so the dashboard can build a trend sparkline as
history accumulates.
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ingest.markets import fetch_quote
from app.ingest.opensky import fetch_airborne_count
from app.repositories.kpi_repository import KpiRepository

logger = get_logger(__name__)

# Static placeholders pending a licensed IATA/OAG/Cirium feed -- fixed at a
# plausible current-industry figure (not randomized) so the dashboard doesn't
# imply more precision than it has.
STATIC_ESTIMATES: dict[str, tuple[float, str, str]] = {
    "passengers_ytd": (2_450_000_000.0, "pax", "Industry estimate (IATA/ICAO feed not connected)"),
    "load_factor": (82.5, "%", "Industry estimate (OAG/Cirium feed not connected)"),
    "cancelled_flights": (450.0, "flights", "Industry estimate (OAG/Cirium feed not connected)"),
}


async def refresh_all_kpis(db: AsyncSession) -> int:
    settings = get_settings()
    repo = KpiRepository(db)
    now = datetime.now(timezone.utc)
    recorded = 0

    airborne = await fetch_airborne_count(settings.opensky_base_url)
    if airborne is not None:
        repo.record("flights_airborne", airborne, "flights", "OpenSky Network", False, now)
        recorded += 1
        # Rough derivation, not a licensed total: at any instant roughly 1/12th
        # of a day's flights are airborne, assuming ~2h average flight duration.
        repo.record(
            "flights_today",
            round(airborne * 12),
            "flights",
            "Derived from OpenSky (est. 2h avg flight duration)",
            True,
            now,
        )
        recorded += 1

    brent = await fetch_quote(settings.yahoo_finance_base_url, "BZ=F")
    if brent is not None:
        repo.record("oil_price", brent, "$/bbl", "Yahoo Finance (BZ=F)", False, now)
        recorded += 1
        # Jet fuel historically trades at a premium ("crack spread") over
        # Brent crude; ~1.18x is a commonly cited rule of thumb, not a
        # licensed jet-fuel index quote.
        repo.record(
            "fuel_price",
            round(brent * 1.18, 2),
            "$/bbl",
            "Derived from Brent crude (est. refining premium)",
            True,
            now,
        )
        recorded += 1

    usd_try = await fetch_quote(settings.yahoo_finance_base_url, "TRY=X")
    if usd_try is not None:
        repo.record("fx_usd_try", usd_try, "", "Yahoo Finance (TRY=X)", False, now)
        recorded += 1

    for metric_key, (value, unit, source) in STATIC_ESTIMATES.items():
        repo.record(metric_key, value, unit, source, True, now)
        recorded += 1

    await db.commit()
    logger.info("kpi_refresh_complete", recorded=recorded)
    return recorded
