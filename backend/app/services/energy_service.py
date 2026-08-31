"""Kokpit's "Yakıt & Enerji" panel: real indicators over real price history.

WHAT THIS IS NOT
----------------
The obvious way to fill an energy panel on an executive dashboard is a "risk
matrix" -- rows like *Oil Supply: High*, *Refining Capacity: Medium*,
*Geopolitical: Elevated*. Every one of those would be invented. This system
ingests price series, not supply balances, refinery utilisation or a
geopolitical risk index, and there is no honest arithmetic from a Brent close
to "Oil Supply: High".

So the panel is filled with things that ARE derivable from the series we
actually have, each one plain arithmetic a reader can re-run:

* week / month / year-to-date change -- the close then versus the close now;
* the 1-year percentile -- where today sits inside its own last 250 sessions,
  the same `percentile_of` the fuel signal tile already bands (imported from
  cockpit_signals_service rather than re-implemented, so the panel and the
  tile can never disagree about where Brent sits in its year);
* 30-day realised volatility -- the annualised standard deviation of daily log
  returns. Realised, not implied: we have no options data, and an implied
  volatility would be a number from a market we do not read.

Anything that could not be computed comes back as None and prints as "—". A
missing indicator is never defaulted to zero, and a series too short to
support one never borrows a longer window to fake it.

JET FUEL
--------
Jet fuel is Brent plus IATA's published crack-spread assumption (see
kpi_service.JET_FUEL_CRACK_SPREAD_USD). Its indicators are computed over the
DERIVED series -- Brent's closes each plus the spread -- not copied from
Brent's own. Adding a constant to a series does not preserve its percentage
changes: at a Brent of 88, a +1$ move is +1.1%, but on jet fuel at 145 the
same move is +0.7%. Copying Brent's percentages onto the jet-fuel row would
have overstated every one of them.
"""
import asyncio
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ingest.markets import fetch_history
from app.services.cockpit_signals_service import percentile_of
from app.services.kpi_service import JET_FUEL_CRACK_SPREAD_USD, LIVE_ENERGY_CONTRACTS

logger = get_logger(__name__)

#: Trading days in a year, for annualising a daily standard deviation. 252 is
#: the conventional figure and is what Yahoo's own 1-year daily series
#: actually returns (~251 sessions), so it is a count of this data rather than
#: a borrowed constant.
TRADING_DAYS_PER_YEAR = 252

#: Sessions in the realised-volatility window. 30 CALENDAR days is ~21
#: sessions; the label says "30g volatilite" because that is the window a
#: reader means, and `VOLATILITY_METHOD_TR` states the session count out loud.
VOLATILITY_SESSIONS = 21

#: Below this many returns the standard deviation is noise, not a volatility.
MIN_VOLATILITY_RETURNS = 10

VOLATILITY_METHOD_TR = (
    "Son 21 işlem gününün günlük logaritmik getirilerinin standart sapması, "
    "252 işlem günü ile yıllıklandırılmıştır. Gerçekleşen (realised) "
    "volatilitedir — opsiyon verisi bu sistemde yoktur, dolayısıyla zımni "
    "(implied) volatilite değildir."
)

PERCENTILE_METHOD_TR = (
    "Bugünkü kapanışın son 1 yılın kapanışları içindeki yüzdelik dilimi. "
    "%100 = son bir yılın en yükseği."
)


@dataclass(frozen=True)
class EnergyIndicators:
    """Everything derivable from one daily close series. Every field is
    Optional and every None means "the series does not support this", never
    "zero"."""

    value: float | None
    as_of: datetime | None
    day_change_pct: float | None
    week_change_pct: float | None
    month_change_pct: float | None
    ytd_change_pct: float | None
    percentile_1y: float | None
    volatility_30d_pct: float | None
    sparkline: list[float]


def pct_change(latest: float, prior: float | None) -> float | None:
    """Signed percent change, or None when there is nothing to compare to.
    A zero prior cannot anchor a percentage -- returning 0 or infinity there
    would both be inventions."""
    if prior is None or prior == 0:
        return None
    return round((latest - prior) / prior * 100, 2)


def _close_at_or_before(points: list[tuple[datetime, float]], cutoff: datetime) -> float | None:
    """The last close at or before `cutoff`, or None when the series does not
    reach that far back. Deliberately NOT "the oldest point we have": a
    "1 aylık değişim" computed against a series only ten days long would be a
    ten-day change wearing a month's label."""
    candidate: float | None = None
    for ts, close in points:
        if ts > cutoff:
            break
        candidate = close
    return candidate


def annualized_volatility(closes: list[float], sessions: int = VOLATILITY_SESSIONS) -> float | None:
    """Annualised standard deviation of daily log returns over the last
    `sessions` closes, in percent.

    None below `MIN_VOLATILITY_RETURNS` returns: a standard deviation over
    three points is arithmetic, but it is not a volatility, and printing one
    would give a number far more confidence than it has earned.
    """
    window = closes[-(sessions + 1) :]
    returns = [
        math.log(curr / prev)
        for prev, curr in zip(window, window[1:], strict=False)
        if prev > 0 and curr > 0
    ]
    if len(returns) < MIN_VOLATILITY_RETURNS:
        return None
    mean = sum(returns) / len(returns)
    # Sample variance (n-1): these returns are a sample of the process, not
    # the whole population of it.
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 1)


def indicators_from_history(
    points: list[tuple[datetime, float]], *, today: date | None = None
) -> EnergyIndicators:
    """Every indicator this panel prints, from one daily close series.

    Pure: no I/O, so each window and each guard is directly unit-testable.
    `points` must be oldest-first, which is what `fetch_history` returns.
    """
    if not points:
        return EnergyIndicators(
            value=None,
            as_of=None,
            day_change_pct=None,
            week_change_pct=None,
            month_change_pct=None,
            ytd_change_pct=None,
            percentile_1y=None,
            volatility_30d_pct=None,
            sparkline=[],
        )

    closes = [close for _, close in points]
    last_ts, latest = points[-1]
    reference = today or last_ts.date()

    day_prior = closes[-2] if len(closes) >= 2 else None
    week_prior = _close_at_or_before(points, last_ts - timedelta(days=7))
    month_prior = _close_at_or_before(points, last_ts - timedelta(days=30))

    # Year-to-date: the last close of the PREVIOUS year, so "YTD" means the
    # calendar year and not "the last 365 days" (which is what month/week
    # already are, rolling). None in early January, when the series has no
    # December close in it -- an honest gap rather than a one-week change
    # labelled YTD.
    year_start = datetime(reference.year, 1, 1, tzinfo=last_ts.tzinfo)
    ytd_prior = _close_at_or_before(points, year_start)

    return EnergyIndicators(
        value=latest,
        as_of=last_ts,
        day_change_pct=pct_change(latest, day_prior),
        week_change_pct=pct_change(latest, week_prior),
        month_change_pct=pct_change(latest, month_prior),
        ytd_change_pct=pct_change(latest, ytd_prior),
        percentile_1y=percentile_of(latest, closes),
        volatility_30d_pct=annualized_volatility(closes),
        # Weekly-ish thinning so a 250-point daily year fits a 56px sparkline
        # without drawing 250 strokes into 56 pixels. Every point plotted is a
        # real close; none is averaged into a bucket.
        sparkline=closes[-1::-5][::-1],
    )


@dataclass(frozen=True)
class EnergyMetric:
    """One row of the panel: the contract, plus everything derived from it."""

    metric_key: str
    label_tr: str
    unit: str
    symbol: str
    source: str
    source_url: str
    href: str
    is_estimate: bool
    note_tr: str | None
    indicators: EnergyIndicators


#: The contracts drawn from their own series, in `LIVE_ENERGY_CONTRACTS`'s own
#: (metric_key, symbol, unit, label) shape so the two lists cannot fall out of
#: step. Brent leads because the jet-fuel row is derived from it.
BRENT_SYMBOL = "BZ=F"

_SOURCED_CONTRACTS: tuple[tuple[str, str, str, str], ...] = (
    ("oil_price", BRENT_SYMBOL, "$/bbl", "Brent"),
    *LIVE_ENERGY_CONTRACTS,
)

JET_FUEL_NOTE_TR = (
    f"Tahmini: Brent + {JET_FUEL_CRACK_SPREAD_USD:.0f}$ crack varsayımı "
    "(IATA Küresel Görünüm, Haziran 2026). Lisanslı bir jet yakıtı endeksi "
    "kotasyonu değildir; tüm yüzdeler bu türetilmiş seri üzerinden hesaplanır."
)


async def energy_metrics() -> list[EnergyMetric]:
    """Brent, WTI, Henry Hub gas and the derived jet-fuel row.

    One Yahoo fetch per real contract (three), each a year of daily closes;
    the jet-fuel row costs no fetch at all because it is Brent's own series
    shifted by the crack spread. `fetch_history` never raises -- it returns []
    on any failure -- so a provider outage thins this panel to "—" instead of
    failing the request.
    """
    settings = get_settings()
    # Three independent providers-of-one-provider calls. Serially this panel
    # paid three ~1s round trips on every cold cache; gathered it pays one.
    histories = await asyncio.gather(
        *(
            fetch_history(settings.yahoo_finance_base_url, symbol, "1y_daily")
            for _, symbol, _, _ in _SOURCED_CONTRACTS
        )
    )

    rows: list[EnergyMetric] = []
    brent_points: list[tuple[datetime, float]] = []

    for (metric_key, symbol, unit, label_tr), points in zip(
        _SOURCED_CONTRACTS, histories, strict=True
    ):
        if metric_key == "oil_price":
            brent_points = points
        rows.append(
            EnergyMetric(
                metric_key=metric_key,
                label_tr=label_tr,
                unit=unit,
                symbol=symbol,
                source=f"Yahoo Finance ({symbol})",
                source_url=f"https://finance.yahoo.com/quote/{symbol}",
                href=f"/kpi/{metric_key}",
                is_estimate=False,
                note_tr=None,
                indicators=indicators_from_history(points),
            )
        )

    # The derived row, inserted right after Brent so the two read together.
    jet_points = [(ts, round(close + JET_FUEL_CRACK_SPREAD_USD, 2)) for ts, close in brent_points]
    rows.insert(
        1,
        EnergyMetric(
            metric_key="fuel_price",
            label_tr="Jet yakıtı ˜",
            unit="$/bbl",
            symbol=BRENT_SYMBOL,
            source=f"Brent + {JET_FUEL_CRACK_SPREAD_USD:.0f}$ crack spread (IATA Haziran 2026)",
            source_url=f"https://finance.yahoo.com/quote/{BRENT_SYMBOL}",
            href="/kpi/fuel_price",
            is_estimate=True,
            note_tr=JET_FUEL_NOTE_TR,
            indicators=indicators_from_history(jet_points),
        ),
    )

    logger.info("energy_metrics_built", rows=len(rows))
    return rows
