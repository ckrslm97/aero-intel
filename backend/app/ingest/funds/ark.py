"""ARK Invest issuer holdings adapter (ARKG).

ARK publishes full daily holdings as public CSVs. The filename has changed
over time ("GENOMIC REVOLUTION MULTISECTOR" -> "GENOMIC REVOLUTION"), so the
fetcher tries the current name first and falls back to the older one.

CAVEAT: finance hosts are blocked at this sandbox's egress proxy, so the file
shape below follows ARK's documented CSV layout and is parsed defensively.
Adapters never raise: any failure logs a warning and returns None.
"""
import csv
import io
from datetime import date, datetime

import httpx

from app.core.logging import get_logger
from app.ingest.funds.base import HoldingRow, HoldingsSnapshot

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(20.0)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}

# Current filename first, then the pre-rename one still seen in older links.
ARKG_FILENAMES = (
    "ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARK_GENOMIC_REVOLUTION_MULTISECTOR_ETF_ARKG_HOLDINGS.csv",
)

DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")
WEIGHT_COLUMNS = ("weight (%)", "weight(%)", "weight")


async def fetch_arkg_holdings(base_url: str) -> HoldingsSnapshot | None:
    """Try each known ARKG CSV URL; first one that returns 200 with a
    parseable CSV wins."""
    for filename in ARKG_FILENAMES:
        url = f"{base_url}/{filename}"
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("ark_fetch_failed", url=url, error=str(exc))
            continue

        snapshot = parse_ark_csv(response.text, source_url=url)
        if snapshot is not None:
            logger.info(
                "ark_fetch_ok", url=url, rows=len(snapshot.rows), as_of=str(snapshot.as_of)
            )
            return snapshot
        logger.warning("ark_parse_failed", url=url)
    return None


def _parse_ark_date(raw: str) -> date | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_weight(raw: str) -> float | None:
    """'9.85%' / '9.85' / ' 9.85 ' -> 9.85; anything non-numeric -> None."""
    try:
        return float(raw.replace("%", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_ark_csv(text: str, source_url: str = "") -> HoldingsSnapshot | None:
    """Pure defensive parse of ARK's daily-holdings CSV.

    Columns (case-insensitive): date, company, ticker, cusip, shares,
    market value ($), weight (%). Footer/disclaimer lines (no ticker AND no
    parseable weight) are skipped. Returns None if nothing parseable remains.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        as_of: date | None = None
        parsed: list[tuple[str, str | None, float]] = []

        for raw_row in reader:
            row = {
                key.strip().lower(): (value or "").strip()
                for key, value in raw_row.items()
                if isinstance(key, str)
            }
            ticker = row.get("ticker", "")
            weight = next(
                (
                    w
                    for w in (_parse_weight(row.get(col, "")) for col in WEIGHT_COLUMNS)
                    if w is not None
                ),
                None,
            )
            if not ticker and weight is None:
                continue  # footer / disclaimer line
            if weight is None:
                continue  # cannot rank a row without a weight
            if as_of is None:
                as_of = _parse_ark_date(row.get("date", ""))
            parsed.append((row.get("company", ""), ticker or None, weight))
    except (KeyError, IndexError, TypeError, ValueError, csv.Error) as exc:
        logger.warning("ark_csv_parse_failed", error=str(exc))
        return None

    if not parsed:
        return None
    if as_of is None:
        logger.warning("ark_as_of_missing")
        as_of = date.today()

    parsed.sort(key=lambda item: item[2], reverse=True)
    rows = [
        HoldingRow(rank=rank, holding_name=name, weight_pct=weight, ticker=ticker)
        for rank, (name, ticker, weight) in enumerate(parsed, start=1)
    ]
    return HoldingsSnapshot(
        as_of=as_of,
        source="ark_funds",
        source_url=source_url,
        rows=rows,
        is_top10_only=False,
    )
