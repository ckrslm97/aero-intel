"""Yahoo Finance quoteSummary adapter for fund profiles (holdings, sector
weights, expense ratio).

Reuse note: price and history for funds come from
``app.ingest.markets.fetch_quote`` / ``fetch_history`` -- do not duplicate
those here. This module only adds the flaky quoteSummary profile fetch, which
needs a cookie+crumb handshake and is EXPECTED to fail often; the service
treats a None return as normal.
"""
import httpx

from app.core.logging import get_logger
from app.ingest.funds.base import FundProfile, HoldingRow

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(15.0)
# quoteSummary rejects bot-looking UAs, so present a real browser string.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
COOKIE_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"


async def fetch_fund_profile(base_url: str, symbol: str) -> FundProfile | None:
    """Cookie+crumb handshake, then quoteSummary. One client so cookies persist."""
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            # Step 1: pick up session cookies; the response status is irrelevant.
            try:
                await client.get(COOKIE_URL)
            except httpx.HTTPError:
                pass  # cookies-or-nothing; the crumb request will tell us either way

            # Step 2: crumb tied to those cookies.
            crumb_response = await client.get(CRUMB_URL)
            crumb_response.raise_for_status()
            crumb = crumb_response.text.strip()
            if not crumb:
                logger.warning("yahoo_quote_summary_empty_crumb", symbol=symbol)
                return None

            # Step 3: the actual quoteSummary call.
            response = await client.get(
                f"{base_url}/{symbol}",
                params={"modules": "topHoldings,fundProfile", "crumb": crumb},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("yahoo_quote_summary_fetch_failed", symbol=symbol, error=str(exc))
        return None

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("yahoo_quote_summary_bad_json", symbol=symbol, error=str(exc))
        return None

    profile = parse_quote_summary(data)
    if profile is None:
        logger.warning("yahoo_quote_summary_parse_failed", symbol=symbol)
    else:
        logger.info(
            "yahoo_quote_summary_fetch_ok",
            symbol=symbol,
            holdings=len(profile.top_holdings),
            sectors=len(profile.sector_weights),
        )
    return profile


def parse_quote_summary(data: dict) -> FundProfile | None:
    """Pure parse of a quoteSummary response; unit-testable without network.

    Missing modules are tolerated -- return whatever was present. Only a
    totally empty result yields None.
    """
    try:
        result = data["quoteSummary"]["result"][0]
        if not isinstance(result, dict):
            return None
    except (KeyError, IndexError, TypeError):
        return None

    top_holdings: list[HoldingRow] = []
    sector_weights: list[tuple[str, float]] = []
    try:
        for i, item in enumerate(result["topHoldings"]["holdings"]):
            top_holdings.append(
                HoldingRow(
                    rank=i + 1,
                    holding_name=item["holdingName"],
                    ticker=item.get("symbol"),
                    weight_pct=float(item["holdingPercent"]["raw"]) * 100,
                )
            )
    except (KeyError, IndexError, TypeError, ValueError):
        top_holdings = []

    try:
        for entry in result["topHoldings"]["sectorWeightings"]:
            # Each entry is a single-key dict: {sector_name: {"raw": x}}.
            for sector_name, value in entry.items():
                sector_weights.append((sector_name, float(value["raw"]) * 100))
    except (KeyError, IndexError, TypeError, ValueError):
        sector_weights = []

    expense_ratio: float | None = None
    try:
        raw = result["fundProfile"]["feesExpensesInvestment"]["annualReportExpenseRatio"]["raw"]
        expense_ratio = float(raw) * 100
    except (KeyError, IndexError, TypeError, ValueError):
        expense_ratio = None

    if not top_holdings and not sector_weights and expense_ratio is None:
        return None

    # topHoldings carries no AUM figure -- aum stays None from this source.
    return FundProfile(
        expense_ratio=expense_ratio,
        aum=None,
        top_holdings=top_holdings,
        sector_weights=sector_weights,
        source="yahoo_quote_summary",
    )
