"""Vanguard issuer holdings adapter (VHT) -- WEAKEST SOURCE, best-effort only.

VHT has NO confirmed keyless holdings endpoint: the URLs below are unofficial,
undocumented, and were NOT verifiable from this sandbox (finance hosts are
blocked at the egress proxy). Every attempt is fully wrapped; a None return is
the *expected* outcome, at which point the service falls back to Yahoo's
top-10 list labeled ``is_top10_only=True`` / ``single_source``.
"""
from datetime import date, datetime

import httpx

from app.core.logging import get_logger
from app.ingest.funds.base import HoldingRow, HoldingsSnapshot

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(20.0)
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,*/*",
}

# (url, extra headers) tried in order; each attempt is independent.
VHT_ENDPOINTS: tuple[tuple[str, dict], ...] = (
    (
        "https://investor.vanguard.com/investment-products/etfs/profile/api/VHT/"
        "portfolio-holding/stock",
        {},
    ),
    (
        "https://api.vanguard.com/rs/ire/01/ind/fund/VHT/portfolio-holding/stock.json",
        {"Referer": "https://investor.vanguard.com"},
    ),
)

AS_OF_KEYS = ("asOfDate", "effectiveDate")
NAME_KEYS = ("longName", "shortName", "name")


async def fetch_vht_holdings() -> HoldingsSnapshot | None:
    for url, extra_headers in VHT_ENDPOINTS:
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers={**BASE_HEADERS, **extra_headers},
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("vanguard_fetch_failed", url=url, error=str(exc))
            continue

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("vanguard_bad_json", url=url, error=str(exc))
            continue

        snapshot = parse_vanguard_json(data, source_url=url)
        if snapshot is not None:
            logger.info(
                "vanguard_fetch_ok",
                url=url,
                rows=len(snapshot.rows),
                as_of=str(snapshot.as_of),
            )
            return snapshot
        logger.warning("vanguard_parse_failed", url=url)
    return None


def _parse_vanguard_date(raw) -> date | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    for candidate, fmt in ((raw[:10], "%Y-%m-%d"), (raw, "%m/%d/%Y")):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").strip())
        except ValueError:
            return None
    return None


def _find_entities(data: dict) -> list | None:
    """Accept {"fund": {"entity": [...]}} or a top-level {"entity": [...]}."""
    for container in (data.get("fund"), data):
        if isinstance(container, dict) and isinstance(container.get("entity"), list):
            return container["entity"]
    return None


def _find_as_of(data: dict, entities: list) -> date | None:
    containers: list = [data]
    if isinstance(data.get("fund"), dict):
        containers.append(data["fund"])
    if entities and isinstance(entities[0], dict):
        containers.append(entities[0])
    for container in containers:
        for key in AS_OF_KEYS:
            parsed = _parse_vanguard_date(container.get(key))
            if parsed is not None:
                return parsed
    return None


def parse_vanguard_json(data, source_url: str = "") -> HoldingsSnapshot | None:
    """Pure defensive parse of Vanguard's (unofficial) portfolio-holding JSON."""
    try:
        if not isinstance(data, dict):
            return None
        entities = _find_entities(data)
        if not entities:
            return None

        parsed: list[tuple[str, str | None, float]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            weight = _to_float(entity.get("percentWeight"))
            if weight is None:
                continue
            name = next(
                (entity[k].strip() for k in NAME_KEYS if isinstance(entity.get(k), str)), ""
            )
            ticker = entity.get("ticker")
            ticker = ticker.strip() if isinstance(ticker, str) and ticker.strip() else None
            parsed.append((name, ticker, weight))

        if not parsed:
            return None

        as_of = _find_as_of(data, entities)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        logger.warning("vanguard_json_parse_failed", error=str(exc))
        return None

    if as_of is None:
        logger.warning("vanguard_as_of_missing")
        as_of = date.today()

    parsed.sort(key=lambda item: item[2], reverse=True)
    rows = [
        HoldingRow(rank=rank, holding_name=name, weight_pct=weight, ticker=ticker)
        for rank, (name, ticker, weight) in enumerate(parsed, start=1)
    ]
    return HoldingsSnapshot(
        as_of=as_of,
        source="vanguard",
        source_url=source_url,
        rows=rows,
        is_top10_only=False,
    )
