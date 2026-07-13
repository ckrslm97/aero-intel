"""Yahoo Finance's public (unauthenticated, undocumented but widely used) chart
endpoint -- one of the "Financial Sources" named in the spec. Used for Brent
crude and FX, both genuinely free and keyless.
"""
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
