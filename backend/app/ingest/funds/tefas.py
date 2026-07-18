"""TEFAS (Turkiye Elektronik Fon Alim Satim Platformu) adapter -- the
SPK/Takasbank-run official fund platform for Turkish mutual funds.

TEFAS is authoritative but has no independent mirror (fundturkey.com.tr is the
same backend behind a different hostname), so the fund service labels data from
here ``official_single_source`` rather than ``verified``.

Operational caveats:

* TEFAS enforces roughly 6 requests/min; callers must pace requests (the fund
  service sleeps between funds -- this module makes exactly one or two HTTP
  calls per invocation and never retries in a loop).
* The endpoints could NOT be probed from the development sandbox (tefas.gov.tr
  is blocked at the egress proxy), so BOTH API generations are implemented and
  parsed defensively: the current JSON API (community-documented by
  pytefas / tefas-crawler >= 2026) is tried first, and the pre-2026 legacy
  ``/api/DB/*`` form-POST API is the fallback. The log line ``tefas_fetch_ok``
  records which generation answered so the first production run reveals the
  real shape.

Adapters never raise: HTTP failures and unparseable payloads are logged and
collapse to ``None`` (see ingest/funds/base.py).
"""
from datetime import date, datetime, timedelta, timezone

import httpx

from app.core.logging import get_logger
from app.ingest.funds.base import AllocationSlice, TefasInfo, TefasPricePoint

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(20.0)
# Browser-like UA + XHR marker: the legacy /api/DB endpoints reject requests
# without them; the new API tolerates both.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

# Key aliases across API generations (legacy UPPERCASE / new camelCase).
DATE_KEYS = ("TARIH", "tarih", "date")
PRICE_KEYS = ("FIYAT", "fiyat", "price", "birimPayDegeri")
TITLE_KEYS = ("FONUNVAN", "fonUnvan", "fundName", "unvan")
AUM_KEYS = ("PORTFOYBUYUKLUK", "portfoyBuyukluk", "fonToplamDeger")
INVESTOR_KEYS = ("KISISAYISI", "kisiSayisi", "yatirimciSayisi")

# Self-describing allocation rows carry the asset class as a value.
ASSET_TYPE_KEYS = ("assetType", "VARLIKTURU", "varlikTuru")
PERCENT_KEYS = ("percentage", "ORAN", "oran")

# Column-per-asset-class allocation rows: TEFAS column code -> Turkish label.
# Unknown codes are kept as raw labels -- data is never dropped silently.
ALLOCATION_CODE_LABELS: dict[str, str] = {
    "HS": "Hisse Senedi",
    "DT": "Devlet Tahvili",
    "KB": "Kamu Borçlanma",
    "OST": "Özel Sektör Tahvili",
    "BYF": "Borsa Yatırım Fonu",
    "YBA": "Yabancı Borçlanma Aracı",
    "YHS": "Yabancı Hisse Senedi",
    "VM": "Vadeli Mevduat",
    "KMH": "Katılım Hesabı",
    "R": "Repo",
    "TR": "Ters Repo",
    "D": "Diğer",
    "KKS": "Kira Sertifikası",
    "GSYKB": "Gayrimenkul Sertifikası",
    "VI": "Vadeli İşlemler Nakit Teminatı",
    "FB": "Fon Katılma Belgesi",
    "KH": "Kıymetli Maden",
}

# Column-mode keys that are metadata, not asset-class weights.
_ALLOCATION_META_KEYS = frozenset(
    key
    for keys in (DATE_KEYS, PRICE_KEYS, TITLE_KEYS, AUM_KEYS, INVESTOR_KEYS)
    for key in keys
) | {"FONKODU", "fonKodu", "fonKod", "FONTIPI", "fonTipi", "fonTuru", "BilFiyat"}


# ---------------------------------------------------------------------------
# Pure parse helpers (unit-testable without network)
# ---------------------------------------------------------------------------


def _parse_tefas_date(value) -> datetime | None:
    """TEFAS dates arrive as ISO strings, ``dd.MM.yyyy`` strings, or
    unix-epoch *milliseconds* (number or numeric string) depending on the API
    generation. Returns a tz-aware UTC datetime, or None if unparseable."""
    if isinstance(value, bool):  # bool is an int subclass, never a date
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # dd.MM.yyyy (legacy request format, sometimes echoed back)
        try:
            return datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # ISO 8601 ("2026-07-18", "2026-07-18T00:00:00Z", ...)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        # Epoch milliseconds as a numeric string ("1689724800000")
        try:
            epoch_ms = float(text)
        except ValueError:
            return None
        try:
            return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    return None


def _first_present(row: dict, keys: tuple[str, ...]):
    """First non-None value among the given alias keys, else None."""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _as_float(value) -> float | None:
    """Number (or numeric string, tolerating Turkish decimal commas) -> float;
    anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        if "," in text:  # "1.234,56" / "12,5" Turkish formatting
            try:
                return float(text.replace(".", "").replace(",", "."))
            except ValueError:
                return None
    return None


def _as_int(value) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None


def _rows_from_payload(payload) -> list | None:
    """Both generations answer either a bare list or ``{"data": [...]}``."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return rows
    return None


def parse_tefas_info_rows(rows) -> TefasInfo | None:
    """Defensive parse of price/info rows from either API generation.

    Accepts a bare list or a ``{"data": [...]}`` wrapper; skips rows missing a
    parseable date or price. None when nothing usable survives."""
    rows = _rows_from_payload(rows)
    if not rows:
        return None

    parsed: list[tuple[datetime, float, dict]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            as_of = _parse_tefas_date(_first_present(row, DATE_KEYS))
            nav = _as_float(_first_present(row, PRICE_KEYS))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if as_of is None or nav is None:
            continue
        parsed.append((as_of, nav, row))

    if not parsed:
        return None

    parsed.sort(key=lambda item: item[0])
    latest = parsed[-1][2]

    title = _first_present(latest, TITLE_KEYS)
    return TefasInfo(
        fund_title=str(title).strip() if title is not None else "",
        points=[TefasPricePoint(as_of=as_of, nav=nav) for as_of, nav, _ in parsed],
        aum=_as_float(_first_present(latest, AUM_KEYS)),
        investor_count=_as_int(_first_present(latest, INVESTOR_KEYS)),
    )


def _column_slices(row: dict) -> list[AllocationSlice]:
    """One-row-per-date allocation shape: each asset class is a column whose
    key is a TEFAS code (``HS``, ``DT``, ...). Unknown codes keep the raw code
    as label; zero/None/non-numeric weights are skipped."""
    slices: list[AllocationSlice] = []
    for key, value in row.items():
        if key in _ALLOCATION_META_KEYS:
            continue
        weight = _as_float(value)
        if weight is None or weight == 0:
            continue
        label = ALLOCATION_CODE_LABELS.get(key) or ALLOCATION_CODE_LABELS.get(
            key.upper(), key
        )
        slices.append(AllocationSlice(label=label, weight_pct=weight))
    return slices


def parse_tefas_allocation_rows(rows) -> tuple[date, list[AllocationSlice]] | None:
    """Defensive parse of allocation rows from either API generation.

    Handles both observed shapes -- self-describing rows (one row per asset
    class, with an asset-type key) and column-per-asset-class rows keyed by
    TEFAS codes. Only the latest date's slices are returned, sorted by weight
    descending. None when nothing usable survives."""
    rows = _rows_from_payload(rows)
    if not rows:
        return None

    dict_rows = [row for row in rows if isinstance(row, dict)]

    # Self-describing shape: {"date": ..., "assetType": "...", "percentage": ...}
    described: list[tuple[datetime, str, float]] = []
    for row in dict_rows:
        asset_type = _first_present(row, ASSET_TYPE_KEYS)
        if asset_type is None:
            continue
        as_of = _parse_tefas_date(_first_present(row, DATE_KEYS))
        weight = _as_float(_first_present(row, PERCENT_KEYS))
        if as_of is None or weight is None or weight == 0:
            continue
        described.append((as_of, str(asset_type).strip(), weight))

    if described:
        latest_dt = max(item[0] for item in described)
        slices = [
            AllocationSlice(label=label, weight_pct=weight)
            for as_of, label, weight in described
            if as_of == latest_dt
        ]
        slices.sort(key=lambda item: item.weight_pct, reverse=True)
        return (latest_dt.date(), slices) if slices else None

    # Column-per-asset-class shape: pick the latest dated row.
    dated_rows: list[tuple[datetime, dict]] = []
    for row in dict_rows:
        as_of = _parse_tefas_date(_first_present(row, DATE_KEYS))
        if as_of is not None:
            dated_rows.append((as_of, row))
    if not dated_rows:
        return None

    dated_rows.sort(key=lambda item: item[0])
    latest_dt, latest_row = dated_rows[-1]
    slices = _column_slices(latest_row)
    if not slices:
        return None
    slices.sort(key=lambda item: item.weight_pct, reverse=True)
    return latest_dt.date(), slices


# ---------------------------------------------------------------------------
# Network layer
# ---------------------------------------------------------------------------


def _legacy_date_range(days: int) -> tuple[str, str]:
    """(start, end) as dd.MM.yyyy strings, ending today (UTC)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y")


async def _request_rows(
    url: str, fon_kod: str, *, json_body: dict | None = None, form_data: dict | None = None
) -> list | None:
    """POST to one TEFAS endpoint, return the row list or None. Never raises."""
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            if json_body is not None:
                response = await client.post(url, json=json_body)
            else:
                response = await client.post(url, data=form_data)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tefas_fetch_failed", url=url, fon_kod=fon_kod, error=str(exc))
        return None

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("tefas_bad_json", url=url, fon_kod=fon_kod, error=str(exc))
        return None

    rows = _rows_from_payload(payload)
    if rows is None:
        logger.warning("tefas_unexpected_payload", url=url, fon_kod=fon_kod)
    return rows


async def fetch_tefas_info(base_url: str, fon_kod: str, months: int = 12) -> TefasInfo | None:
    """Fund title, NAV history, AUM and investor count for one TEFAS fund.

    Tries the current JSON API first, falls back to the pre-2026 legacy
    form-POST API; logs which generation answered. None if both fail."""
    rows = await _request_rows(
        f"{base_url}/api/funds/fonGnlBlgSiraliGetir",
        fon_kod,
        json_body={"fonTuru": "YAT", "fonKod": fon_kod, "sonAy": months},
    )
    info = parse_tefas_info_rows(rows)
    generation = "new"

    if info is None:
        start, end = _legacy_date_range(months * 30)
        rows = await _request_rows(
            f"{base_url}/api/DB/BindHistoryInfo",
            fon_kod,
            form_data={"fontip": "YAT", "fonkod": fon_kod, "bastarih": start, "bittarih": end},
        )
        info = parse_tefas_info_rows(rows)
        generation = "legacy"

    if info is None:
        logger.warning("tefas_info_unavailable", fon_kod=fon_kod)
        return None

    logger.info(
        "tefas_fetch_ok", fon_kod=fon_kod, api_generation=generation, points=len(info.points)
    )
    return info


async def fetch_tefas_allocation(
    base_url: str, fon_kod: str
) -> tuple[date, list[AllocationSlice]] | None:
    """Latest asset-allocation breakdown for one TEFAS fund, as
    (as-of date, slices sorted by weight desc). None if both APIs fail."""
    rows = await _request_rows(
        f"{base_url}/api/funds/dagilimSiraliGetirT",
        fon_kod,
        json_body={"fonTuru": "YAT", "fonKod": fon_kod, "sonAy": 1},
    )
    allocation = parse_tefas_allocation_rows(rows)
    generation = "new"

    if allocation is None:
        start, end = _legacy_date_range(30)
        rows = await _request_rows(
            f"{base_url}/api/DB/BindHistoryAllocation",
            fon_kod,
            form_data={"fontip": "YAT", "fonkod": fon_kod, "bastarih": start, "bittarih": end},
        )
        allocation = parse_tefas_allocation_rows(rows)
        generation = "legacy"

    if allocation is None:
        logger.warning("tefas_allocation_unavailable", fon_kod=fon_kod)
        return None

    logger.info(
        "tefas_fetch_ok",
        fon_kod=fon_kod,
        api_generation=generation,
        points=len(allocation[1]),
    )
    return allocation
