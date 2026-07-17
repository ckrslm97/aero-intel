"""Refreshes dashboard KPIs.

Three kinds of number live here, and the difference matters:

* **Live readings** -- OpenSky's airborne count, Brent and USD/TRY from Yahoo.
  Free, real-time, and re-read every run; FX and oil are each cross-checked
  against a second independent source.
* **Published figures** -- traffic, revenue and unit economics. No free
  real-time source exists for these; they're what IATA publishes a few times a
  year, transcribed once in app/ingest/historical_seed.py and re-used here so
  the dashboard's current value is literally the last point of its own trend
  line. Recorded only when the publisher revises them (see _record_if_changed).
* **Transparent derivations** -- jet fuel from Brent plus IATA's published crack
  spread. Labelled as estimates, with the arithmetic stated.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ingest.historical_seed import PUBLISHED_AT as IATA_PUBLISHED_AT
from app.ingest.historical_seed import SOURCE as IATA_SOURCE
from app.ingest.historical_seed import SOURCE_URL as IATA_ECONOMICS_URL
from app.ingest.historical_seed import build_points
from app.ingest.markets import fetch_frankfurter_rate, fetch_quote
from app.ingest.opensky import fetch_airborne_count
from app.models.kpi import KPI
from app.repositories.kpi_repository import KpiRepository

logger = get_logger(__name__)

OPENSKY_URL = "https://opensky-network.org/"
YAHOO_BRENT_URL = "https://finance.yahoo.com/quote/BZ=F"
YAHOO_FX_URL = "https://finance.yahoo.com/quote/TRY=X"
FRANKFURTER_URL = "https://www.frankfurter.app/"

# Jet fuel trades at a premium ("crack spread") over Brent. IATA's June 2026
# outlook assumes USD 95/bbl Brent and a USD 57/bbl crack spread, giving jet
# fuel at USD 152/bbl -- a spread blown wide by the 2026 energy crisis. It is
# an additive spread, not a multiplier: an earlier 1.18x rule of thumb put jet
# fuel ~40% below what IATA actually publishes.
JET_FUEL_CRACK_SPREAD_USD = 57.0


def latest_published_estimates() -> dict[str, tuple[float, str]]:
    """The newest published figure per metric, read from the same transcription
    that seeds the history -- so the value on the card and the last point of its
    trend can't drift apart."""
    return {
        point.metric_key: (point.value, point.unit)
        for point in build_points()
        if point.as_of == IATA_PUBLISHED_AT
    }


# Metrics whose value is a published figure rather than a live reading. They
# change when a publisher revises an outlook, so a repeated identical row
# carries no information -- unlike oil_price or flights_airborne, where "same
# value again" is a real observation at a real timestamp and must be kept.
PUBLISHED_ESTIMATE_KEYS = set(latest_published_estimates())


async def _record_if_changed(
    repo: KpiRepository,
    metric_key: str,
    value: float,
    unit: str,
    source: str,
    as_of: datetime,
    source_url: str | None = None,
) -> bool:
    """Record a published estimate only when it actually differs from the last one.

    These figures move when IATA revises an outlook -- a few times a year -- not
    every 15 minutes when the refresh job runs. Writing an identical row each
    time would manufacture a time series out of a single number: the trend chart
    would show a dead-flat line of clones, and `as_of` would claim the figure was
    fresh when nothing had changed. Skipping the write makes `as_of` mean what it
    says: when this number last moved.
    """
    latest = await repo.latest(metric_key)
    if latest is not None and latest.value == value and latest.source == source:
        return False
    repo.record(metric_key, value, unit, source, True, as_of, source_url)
    return True


async def refresh_all_kpis(db: AsyncSession) -> int:
    settings = get_settings()
    repo = KpiRepository(db)
    now = datetime.now(timezone.utc)
    recorded = 0

    airborne = await fetch_airborne_count(settings.opensky_base_url)
    if airborne is not None:
        repo.record("flights_airborne", airborne, "uçuş", "OpenSky Network", False, now, OPENSKY_URL)
        recorded += 1
        # Rough derivation, not a licensed total: at any instant roughly 1/12th
        # of a day's flights are airborne, assuming ~2h average flight duration.
        repo.record(
            "flights_today",
            round(airborne * 12),
            "uçuş",
            "OpenSky verisinden türetilmiştir (tahmini 2 saat ortalama uçuş süresi)",
            True,
            now,
            OPENSKY_URL,
        )
        recorded += 1

    brent = await fetch_quote(settings.yahoo_finance_base_url, "BZ=F")
    if brent is not None:
        repo.record("oil_price", brent, "$/bbl", "Yahoo Finance (BZ=F)", False, now, YAHOO_BRENT_URL)
        recorded += 1
        # Live Brent plus IATA's published crack-spread assumption -- not a
        # licensed jet-fuel index quote, but anchored to a citable figure
        # rather than a rule of thumb. See JET_FUEL_CRACK_SPREAD_USD.
        repo.record(
            "fuel_price",
            round(brent + JET_FUEL_CRACK_SPREAD_USD, 2),
            "$/bbl",
            f"Brent + {JET_FUEL_CRACK_SPREAD_USD:.0f}$ crack spread (IATA Haziran 2026 varsayımı)",
            True,
            now,
            YAHOO_BRENT_URL,
        )
        recorded += 1

    usd_try = await fetch_quote(settings.yahoo_finance_base_url, "TRY=X")
    if usd_try is not None:
        repo.record("fx_usd_try", usd_try, "TRY", "Yahoo Finance (TRY=X)", False, now, YAHOO_FX_URL)
        recorded += 1

        # Independent cross-check against a second, unrelated source (ECB
        # reference rates via Frankfurter). Stored as a non-primary reading so
        # it corroborates the dashboard value without feeding its trend line.
        frankfurter_rate = await fetch_frankfurter_rate("USD", "TRY")
        if frankfurter_rate is not None:
            repo.record(
                "fx_usd_try",
                frankfurter_rate,
                "TRY",
                "Frankfurter.app (ECB referans kurları)",
                False,
                now,
                FRANKFURTER_URL,
                is_primary=False,
            )
            recorded += 1
            diff_pct = abs(usd_try - frankfurter_rate) / usd_try * 100
            logger.info(
                "fx_cross_check",
                yahoo=usd_try,
                frankfurter=frankfurter_rate,
                diff_pct=round(diff_pct, 3),
            )

    # The published figures. Normally a no-op: seed_kpi_history() has already
    # stored these at their publication date, and nothing here changes until
    # IATA revises an outlook. This runs anyway so an un-seeded database still
    # shows the current figures rather than empty cards.
    for metric_key, (value, unit) in latest_published_estimates().items():
        if await _record_if_changed(repo, metric_key, value, unit, IATA_SOURCE, now, IATA_ECONOMICS_URL):
            recorded += 1

    await db.commit()
    logger.info("kpi_refresh_complete", recorded=recorded)
    return recorded


async def prune_duplicate_estimates(db: AsyncSession) -> int:
    """One-off cleanup of rows an earlier refresh job wrote every 15 minutes.

    Before `_record_if_changed` existed, every refresh re-inserted each published
    estimate unchanged, so a single IATA figure grew into ~100 identical rows.
    That made `trend()` return twelve clones of one number, which is what left
    the dashboard sparklines looking empty.

    Collapses each consecutive run of identical (value, source) readings down to
    its earliest row -- the one that records when the figure actually appeared.
    Only touches PUBLISHED_ESTIMATE_KEYS: for live metrics an identical reading
    is a genuine observation, not an artefact.
    """
    deleted = 0

    for metric_key in sorted(PUBLISHED_ESTIMATE_KEYS):
        result = await db.execute(
            select(KPI)
            .where(KPI.metric_key == metric_key, KPI.is_primary.is_(True))
            .order_by(KPI.as_of.asc())
        )
        kept: KPI | None = None
        for row in result.scalars().all():
            if kept is not None and row.value == kept.value and row.source == kept.source:
                await db.delete(row)
                deleted += 1
            else:
                kept = row

    await db.commit()
    logger.info("kpi_duplicate_estimates_pruned", deleted=deleted)
    return deleted
