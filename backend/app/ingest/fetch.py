"""The fetch layer for carrier-owned sources: one result type, three ways to get one.

Everything in this module returns a `FetchResult` and nothing in it raises.
That is the same contract `deep_scan._fetch_page` has always had -- every
failure mode of someone else's website becomes a row in `scrape_runs` rather
than an exception that costs six other carriers their run -- and it is stated
once here so the browser, the impersonated GET and the JSON API paths all
classify through the same `deep_scan.classify_outcome`.

Why an impersonated GET exists at all
-------------------------------------
`promo_scrape.py` and `carriers.py` both recorded the same measurement for TK,
AJet, Qatar and Etihad: an HTTP/2 stream reset mid-request, and a silent hang
when forced down to HTTP/1.1. Both files concluded "TK fingerprints below the
HTTP layer", and both were right about the *layer* and wrong about the
consequence. The wall is a TLS fingerprint (JA3/JA4 -- cipher suite order,
extension order, ALPN, the HTTP/2 SETTINGS frame), not an IP reputation check
and not a missing header. Python's ssl module produces one fingerprint,
Chrome's BoringSSL produces another, and these origins accept exactly one of
the two. httpx cannot change that; neither can any User-Agent.

`curl_cffi` can: it is libcurl built against BoringSSL with Chrome's exact
handshake shape, so `impersonate="chrome"` presents the fingerprint the wall is
looking for. Measured against the real origins while this module was written:

    https://www.turkishairlines.com/tr-tr/kampanyalar/   200, server-rendered
    https://www.etihad.com/en/offers                     200, JS-rendered cards
    https://www.qatarairways.com/en/offers.html          200, JS-rendered cards

Only the first of those three is useful without a browser -- see `carriers.py`
for why QR and EY stay on the browser method despite answering 200 here.

**The honest caveat, and why the telemetry matters.** Every one of those
measurements was taken from a Turkish residential IP. The scheduled job runs
from GitHub's Azure ranges, and these WAFs score datacentre egress differently:
a TLS fingerprint that passes from a home connection can still be refused from
a cloud ASN, because the two signals are combined rather than checked in turn.
So this module is a hypothesis with strong local evidence, not a promise. The
`scrape_runs` rows it writes are the experiment -- a TK row that comes back
`blocked` from Actions while it is `ok` from a laptop is the answer to the
residential-vs-Azure question, and it costs one HTTP request a day to get.

curl_cffi is imported lazily, exactly as playwright is in `deep_scan`: an
environment without the binary wheel gets a logged `unavailable` result, never
an ImportError at module import time.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

#: curl_cffi's browser target. "chrome" tracks the newest Chrome profile the
#: installed version ships, which is what we want: pinning to a specific build
#: ("chrome124") would freeze our fingerprint while real Chrome moves on, and a
#: fingerprint that matches no living browser is more suspicious than one that
#: matches this month's.
DEFAULT_IMPERSONATE = "chrome"

#: Generous, because these are heavy marketing pages behind a CDN; finite,
#: because a hang is TK's other documented failure mode and a timeout has to be
#: recordable as one.
DEFAULT_TIMEOUT_S = 25.0

#: JSON gateways answer in well under a second when they answer at all.
API_TIMEOUT_S = 20.0

#: Sent on the httpx paths. Not a disguise -- curl_cffi is what gets past a
#: fingerprint check, and a header cannot -- but singaporeair.com answers
#: **HTTP 404** to httpx's default `python-httpx/0.28.1` on an endpoint that
#: returns 200 to any browser string. A 404 reads as "the URL is wrong" all the
#: way through classify_outcome, which would have retired a working source as a
#: bad path. Same reason promo_scrape.py sends one.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchResult:
    """What a fetch got back, before anything is decided about it.

    Separated from classification (`deep_scan.classify_outcome`) so the whole
    outcome/hash/change-detection half of the scanner is testable without a
    browser, a network or a TLS stack -- which is the only way it can be tested
    at all, since CI has no route to these origins.

    Lives here rather than in `deep_scan` because it is now the shared currency
    of three fetch methods, not just the browser one; `deep_scan` re-exports it
    so existing imports keep working.
    """

    text: str | None
    http_status: int | None = None
    error: str | None = None
    timed_out: bool = False
    #: Parsed JSON body, when the caller asked for one. Kept beside `text`
    #: rather than replacing it because `text` is what gets hashed for change
    #: detection and what the challenge detector reads.
    payload: object | None = None


def curl_cffi_available() -> bool:
    """Whether the impersonating HTTP client can be used at all.

    Checked rather than assumed: `requirements.txt` pins it, but a Vercel build
    that trims wheels or a developer on an unsupported platform must degrade to
    a logged no-op rather than crashing the import of every ingest module.
    """
    try:
        import curl_cffi.requests  # noqa: F401
    except Exception:  # noqa: BLE001 -- a broken wheel is as good as a missing one
        return False
    return True


async def impersonated_get(
    url: str,
    *,
    impersonate: str = DEFAULT_IMPERSONATE,
    timeout: float = DEFAULT_TIMEOUT_S,
    headers: dict[str, str] | None = None,
    session_factory=None,
) -> FetchResult:
    """GET `url` with a real browser's TLS fingerprint. Never raises.

    `session_factory` is the seam the tests use: production passes nothing and
    gets `curl_cffi.requests.AsyncSession`, so no test ever opens a socket.

    Redirects are followed -- every one of these carriers redirects a bare
    locale path at least once -- and the response is returned whatever its
    status, because a 403 with a body is a wall and `classify_outcome` is the
    one place that decides what a status means.
    """
    if session_factory is None:
        try:
            from curl_cffi.requests import AsyncSession
        except Exception as exc:  # noqa: BLE001 -- see curl_cffi_available
            logger.warning("impersonated_get_unavailable", url=url, error=str(exc))
            return FetchResult(text=None, error=f"curl_cffi kullanılamıyor: {exc}")
        session_factory = AsyncSession

    try:
        async with session_factory() as session:
            response = await session.get(
                url,
                impersonate=impersonate,
                timeout=timeout,
                headers=headers or {},
                allow_redirects=True,
            )
        return FetchResult(text=response.text, http_status=response.status_code)
    except Exception as exc:  # noqa: BLE001 -- every failure becomes a scrape_runs row
        message = f"{type(exc).__name__}: {exc}"
        return FetchResult(text=None, error=message, timed_out=_looks_like_timeout(exc))


def _looks_like_timeout(exc: BaseException) -> bool:
    """True for the several unrelated classes that all mean "it never answered".

    Matched on name and message rather than on type, for the same reason
    `deep_scan.is_timeout_error` is: curl_cffi may not be installed, so its
    exception classes cannot be named in an isinstance check here.
    """
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__.casefold()
    return "timeout" in name or "timeout" in str(exc).casefold()


async def json_post(
    url: str,
    payload: dict,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = API_TIMEOUT_S,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """POST JSON, expect JSON back. Never raises.

    Plain httpx on purpose: the one JSON gateway this product reads (AJet's
    CMS, see `ajet_campaigns.py`) has no TLS wall in front of it at all, and
    reaching for the impersonating client where it is not needed would spend a
    heavier dependency and a slower handshake to buy nothing.
    """
    return await _json_request("POST", url, json=payload, client=client, timeout=timeout, headers=headers)


async def json_get(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = API_TIMEOUT_S,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """GET a JSON endpoint. Never raises. See `json_post`."""
    return await _json_request("GET", url, client=client, timeout=timeout, headers=headers)


async def _json_request(
    method: str,
    url: str,
    *,
    client: httpx.AsyncClient | None,
    timeout: float,
    headers: dict[str, str] | None,
    json: dict | None = None,
) -> FetchResult:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True)
    try:
        response = await client.request(
            method,
            url,
            json=json,
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": BROWSER_UA,
                **(headers or {}),
            },
        )
    except httpx.TimeoutException as exc:
        return FetchResult(text=None, error=f"{type(exc).__name__}: {exc}", timed_out=True)
    except Exception as exc:  # noqa: BLE001 -- every failure becomes a row
        return FetchResult(text=None, error=f"{type(exc).__name__}: {exc}")
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        # The body is kept: a WAF's challenge page arrives with a status too,
        # and `classify_outcome` reads both.
        return FetchResult(text=response.text, http_status=response.status_code)

    try:
        parsed = response.json()
    except ValueError as exc:
        # 200 + HTML is the documented shape of a dead feed (see
        # sources_seed.py's SHGM note). A JSON endpoint that stops returning
        # JSON is a parse_error, not a success with no campaigns.
        return FetchResult(
            text=response.text,
            http_status=response.status_code,
            error=f"JSON çözümlenemedi: {exc}",
        )
    return FetchResult(text=response.text, http_status=response.status_code, payload=parsed)
