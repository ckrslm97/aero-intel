"""Yahoo Finance's public (unauthenticated, undocumented but widely used) chart
endpoint -- one of the "Financial Sources" named in the spec. Used for Brent
crude and FX, both genuinely free and keyless. Frankfurter.app (ECB reference
rates) backs a second, independent FX reading so USD/TRY is genuinely
cross-verified rather than taken from a single source.
"""
from datetime import datetime, timezone

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(15.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (AeroIntel KPI fetcher)"}


async def fetch_quote(base_url: str, symbol: str) -> float | None:
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=HEADERS) as client:
            response = await client.get(f"{base_url}/{symbol}")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("yahoo_finance_fetch_failed", symbol=symbol, error=str(exc))
        return None

    try:
        data = response.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        logger.info("yahoo_finance_fetch_ok", symbol=symbol, price=price)
        return float(price)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("yahoo_finance_parse_failed", symbol=symbol, error=str(exc))
        return None


# UI period -> Yahoo Finance (range, interval) query params.
HISTORY_RANGES: dict[str, tuple[str, str]] = {
    "1w": ("5d", "15m"),
    "1m": ("1mo", "1d"),
    "3m": ("3mo", "1d"),
    "6m": ("6mo", "1wk"),
    "1y": ("1y", "1wk"),
    "1y_daily": ("1y", "1d"),  # /invest module needs daily granularity for 1-year fund charts
}


async def fetch_history(
    base_url: str, symbol: str, period: str
) -> list[tuple[datetime, float]]:
    """Real historical closes from Yahoo Finance for the given UI period
    (1w/1m/3m/6m/1y) -- these don't depend on how long *we've* been recording,
    unlike metrics with no external historical source (see kpi history API)."""
    range_param, interval = HISTORY_RANGES.get(period, ("1mo", "1d"))

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=HEADERS) as client:
            response = await client.get(
                f"{base_url}/{symbol}", params={"range": range_param, "interval": interval}
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("yahoo_finance_history_fetch_failed", symbol=symbol, error=str(exc))
        return []

    try:
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("yahoo_finance_history_parse_failed", symbol=symbol, error=str(exc))
        return []

    points: list[tuple[datetime, float]] = []
    for ts, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        points.append((datetime.fromtimestamp(ts, tz=timezone.utc), float(close)))
    return points


async def fetch_frankfurter_rate(base_currency: str, quote_currency: str) -> float | None:
    """Independent FX cross-check: ECB reference rates via frankfurter.app
    (free, keyless, no rate limit published)."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                "https://api.frankfurter.dev/v1/latest",
                params={"from": base_currency, "to": quote_currency},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("frankfurter_fetch_failed", error=str(exc))
        return None

    try:
        rate = response.json()["rates"][quote_currency]
        logger.info("frankfurter_fetch_ok", pair=f"{base_currency}/{quote_currency}", rate=rate)
        return float(rate)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("frankfurter_parse_failed", error=str(exc))
        return None
