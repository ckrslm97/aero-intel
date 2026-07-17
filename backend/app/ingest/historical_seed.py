"""Real published history for the KPIs that have no live feed.

Most dashboard metrics (traffic, revenue, unit economics) simply have no free
real-time source -- they exist as figures an industry body publishes a few times
a year. Before this seed the app stored one such figure and re-recorded it every
15 minutes, which turned a single number into a fake time series and rendered as
a flat line.

So the history here is transcribed from one citable document: IATA's *Global
Outlook for Air Transport, June 2026* ("Energy in Crisis"), Tables 4, 6 and 7,
which carry the industry series from 2019 through a 2026 forecast. Every value
below is either verbatim from that report or arithmetic on it (see DERIVED
below) -- nothing is estimated, interpolated or invented. Re-runnable: points
already stored at the same timestamp are skipped.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.kpi_repository import KpiRepository

logger = get_logger(__name__)

SOURCE = "IATA Küresel Görünüm (Haziran 2026)"
SOURCE_URL = (
    "https://www.iata.org/en/publications/economics/reports/"
    "global-outlook-for-air-transport-june-2026/"
)

# Published 2026-06-07 at IATA's 82nd AGM. The 2026 column is a forecast and the
# 2025 column an estimate, so both are dated to publication rather than to a
# 31 December that hasn't happened yet.
PUBLISHED_AT = datetime(2026, 6, 7, tzinfo=timezone.utc)

YEARS = (2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)

# --- Table 4: key passenger traffic metrics (verbatim) ---
RPK_BILLION = (8688, 2974, 3623, 5973, 8171, 9038, 9520, 9719)
PASSENGERS_MILLION = (4560, 1779, 2304, 3452, 4414, 4781, 4967, 5085)
LOAD_FACTOR_PCT = (82.6, 65.2, 66.9, 78.7, 82.2, 83.4, 83.5, 84.0)
DEPARTURES_MILLION = (37.5, 19.7, 24.2, 29.5, 35.3, 37.3, 38.9, 38.7)

# --- Table 6: key industry finance metrics, USD billion (verbatim) ---
PASSENGER_REVENUE_BN = (607, 189, 242, 437, 669, 726, 768, 839)
CARGO_REVENUE_BN = (101, 140, 210, 206, 139, 147, 151, 162)
ANCILLARY_REVENUE_BN = (130, 55, 61, 95, 122, 137, 146, 165)
EBIT_BN = (43.1, -110.9, -43.5, 11.3, 66.1, 70.7, 76.4, 48.0)

# DERIVED -- arithmetic on the rows above, using IATA's own definitions:
#   ASK   = RPK / passenger load factor      (load factor is defined as RPK/ASK)
#   yield = passenger revenue / RPK
#   RASK  = total revenue / ASK              (total = passenger + cargo + ancillary)
#   CASK  = total expenses / ASK             (expenses = total revenue - EBIT)
# Each reproduces a figure IATA states independently, which is why these are
# safe to publish: the derived 2026 yield (8.63c) matches IATA's published +7.0%
# YoY change, derived 2026 expenses ($1,118bn) match its stated fuel + non-fuel
# costs ($350bn + $767bn), and derived 2026 total revenue ($1,166bn) matches its
# headline $1.165 trillion. See test_historical_seed.py, which asserts exactly this.

BILLION = 1_000_000_000
MILLION = 1_000_000


@dataclass(frozen=True)
class SeedPoint:
    metric_key: str
    value: float
    unit: str
    as_of: datetime


def _as_of(year: int) -> datetime:
    """Date each point to the period it describes; the current year's forecast
    is dated to publication instead of a future 31 December."""
    if year >= PUBLISHED_AT.year:
        return PUBLISHED_AT
    return datetime(year, 12, 31, tzinfo=timezone.utc)


def build_points() -> list[SeedPoint]:
    points: list[SeedPoint] = []

    for i, year in enumerate(YEARS):
        as_of = _as_of(year)
        rpk_bn = RPK_BILLION[i]
        load_factor = LOAD_FACTOR_PCT[i]
        ask_bn = rpk_bn / (load_factor / 100)
        pax_rev_bn = PASSENGER_REVENUE_BN[i]
        ancillary_bn = ANCILLARY_REVENUE_BN[i]
        total_rev_bn = pax_rev_bn + CARGO_REVENUE_BN[i] + ancillary_bn
        total_cost_bn = total_rev_bn - EBIT_BN[i]

        points.extend(
            [
                SeedPoint("passengers_ytd", PASSENGERS_MILLION[i] * MILLION, "yolcu", as_of),
                SeedPoint("load_factor", load_factor, "%", as_of),
                SeedPoint("rpk", rpk_bn * BILLION, "RPK", as_of),
                SeedPoint("ask", round(ask_bn) * BILLION, "ASK", as_of),
                SeedPoint("departures", DEPARTURES_MILLION[i] * MILLION, "kalkış", as_of),
                SeedPoint("passenger_revenue_ytd", pax_rev_bn * BILLION, "$", as_of),
                SeedPoint("ancillary_revenue_ytd", ancillary_bn * BILLION, "$", as_of),
                SeedPoint(
                    "total_aviation_revenue_ytd", (pax_rev_bn + ancillary_bn) * BILLION, "$", as_of
                ),
                SeedPoint("yield_per_rpk", round(pax_rev_bn / rpk_bn * 100, 2), "¢/RPK", as_of),
                SeedPoint("rask", round(total_rev_bn / ask_bn * 100, 2), "¢/ASK", as_of),
                SeedPoint("cask", round(total_cost_bn / ask_bn * 100, 2), "¢/ASK", as_of),
            ]
        )

    return points


async def seed_kpi_history(db: AsyncSession) -> int:
    """Insert any published point that isn't stored yet. Idempotent."""
    repo = KpiRepository(db)
    inserted = 0

    for point in build_points():
        if await repo.exists_at(point.metric_key, point.as_of):
            continue
        repo.record(
            point.metric_key,
            point.value,
            point.unit,
            SOURCE,
            is_estimate=True,  # a published industry figure, not a live reading
            as_of=point.as_of,
            source_url=SOURCE_URL,
        )
        inserted += 1

    await db.commit()
    logger.info("kpi_history_seeded", inserted=inserted)
    return inserted
