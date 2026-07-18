"""stockanalysis.com ETF quote adapter -- price cross-check only (the
"Frankfurter role" for ETFs: a second, independent price reading).

CAVEAT: this endpoint could NOT be verified from the development sandbox (all
finance hosts are blocked at the egress proxy), so the response shape below is
an educated guess parsed defensively. A None return simply degrades the price
row to ``single_source`` -- it never fabricates a value.
"""
import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(15.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (AeroIntel KPI fetcher)"}

# Keys we consider plausible carriers of the last price, in preference order.
PRICE_KEYS = ("price", "cl", "last", "close", "c")


async def fetch_price_cross_check(base_url: str, symbol: str) -> float | None:
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(f"{base_url}/e/{symbol.lower()}")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("stockanalysis_fetch_failed", symbol=symbol, error=str(exc))
        return None

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("stockanalysis_bad_json", symbol=symbol, error=str(exc))
        return None

    price = parse_stockanalysis_quote(data)
    if price is None:
        logger.warning("stockanalysis_parse_failed", symbol=symbol)
    return price


def _as_positive_float(value) -> float | None:
    """Positive number (or numeric string) -> float; anything else -> None."""
    if isinstance(value, bool):  # bool is an int subclass; True is not a price
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def parse_stockanalysis_quote(data) -> float | None:
    """Pure defensive parse of the unofficial quote payload.

    Accepts ``{"data": {...}}`` wrappers and scans for the first plausible
    price key holding a positive number. Logs which key matched at info level
    so the first production run reveals the real shape.
    """
    if not isinstance(data, dict):
        return None
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return None

    for key in PRICE_KEYS:
        if key in inner:
            price = _as_positive_float(inner[key])
            if price is not None:
                logger.info("stockanalysis_price_key_matched", key=key, price=price)
                return price
    return None
