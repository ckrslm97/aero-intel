"""Fetches every carrier campaign source that `promo_scrape.py` cannot, by
whatever means each one needs, and answers one question per source: has it
changed since we last read it?

Three fetch methods now, not one, and the split is the point (see
app/ingest/carriers.py for which carrier uses which):

  * **api** -- AJet and Singapore Airlines publish structured JSON. One httpx
    call, campaigns already in labelled fields, and no model call at all.
  * **impersonate** -- TK's page is server-rendered and was never unreadable;
    it was refusing our TLS fingerprint. One curl_cffi call, then the LLM chain
    over the parsed campaign blocks.
  * **browser** -- QR, EY, EK and BA render their offer cards client-side, so
    the bytes are not enough even when they arrive. Chromium, then the chain.

The cheap two run first and unconditionally: a runner that cannot install a
browser still comes back with three carriers' campaigns.

The change-detection ledger is what keeps the LLM budget honest. The Groq free
tier is a shared ceiling across the whole product, and a campaign page that has
not changed since this morning has nothing new to extract from it. So every
source is reduced to text, hashed, and compared against the last successful
hash for its URL; `scrape_runs.changed` is what decides whether extraction runs
at all.

Three decisions worth knowing before reading the code:

**The hash is over extracted text, never raw HTML.** A rotating hero image, a
regenerated CSS bundle hash or a reordered tracking attribute changes the HTML
on every single load and none of them change the campaign. Hashing the markup
would report "changed" twice a day forever and turn the LLM budget into a
random number generator. Where a carrier has a known campaign-block selector
the hash narrows further, to just those blocks.

**A changed page is recorded, not stored.** `scrape_runs` has no text column,
by design -- it is a run log, two rows per carrier per day, and hanging a full
page body off every row would make the cheapest table in the schema the
largest. Extraction therefore runs *inside* this sweep, against the text this
run already has in memory, and never re-fetches within a run. Only a re-run
across days would have to load the page again, which is the trade-off the
schema was merged with.

That reverses this module's original note that an LLM call does not belong in
the courtesy loop, and the reversal is deliberate: the call does hold a browser
context open for a second or two, and the alternative was a second page load
per changed page on origins that barely tolerate the first one. A context
sitting idle costs us memory; a duplicate fetch costs the carrier -- and the
2-4s courtesy pause between pages already dwarfs the call anyway.

**A page is only baselined once its campaigns are in the table.** The change
detection above is a ledger with one entry per URL: `latest_ok_hash` reads the
newest `ok` run that carries a hash, and `decide_changed` compares against it.
So writing this run's hash means "everything this page now says has been dealt
with". When extraction is enabled and a changed page is *not* dealt with --
the LLM budget ran out, the model returned unparseable JSON, no model is
configured -- the run is still recorded, still `ok`, still `changed=True`, but
its `content_hash` is withheld and the reason goes in `error`. The next run
then compares against the older baseline, finds the page changed again, and
retries. Without that, a page whose extraction was capped would be marked
unchanged forever and its campaigns would never be read at all.

The converse case is left alone on purpose: with extraction disabled (the flag
off, or `--dry-run`) this module is in pure telemetry mode and records hashes
exactly as it did before, because the change counters are what the bot-wall
go/no-go gate is read from. The cost is stated rather than hidden: the first
run after the flag is turned on adopts the baselines telemetry-only runs left
behind, so it extracts the pages that change from then on rather than
everything standing.

**A dry run still writes telemetry.** `--dry-run` suppresses the hand-off to
extraction, not the run log -- the point of the first dispatch was to read
`scrape_runs` and find out which walls a real Chromium gets through, and the
point of the next one is to find out whether the TLS fingerprint that works
from a residential IP also works from GitHub's Azure ranges (app/ingest/fetch.py
states that caveat in full). A dry run that recorded nothing could not answer
either question.

Robots courtesy: this fetches one to two first-party sources per carrier, twice
a day, sequentially, with a 2-4s pause between browser page loads (0.5-1.5s
between the JSON calls, which cost the other end far less) and one browser
context per carrier. That is roughly a dozen requests a day across eight
airlines -- below what a single interested customer generates, and far below
any threshold a crawl-delay is meant to protect.

Playwright is a dev-only dependency (backend/requirements-dev.txt); it is
installed on the Actions runner that runs the deep-scan workflow and is not
part of the serverless API's install. The import is therefore lazy and its
absence is a logged no-op, exactly as in app/pdf/render.py -- importing this
module must never be what breaks an environment that has no browser.
"""
import asyncio
import hashlib
import random
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.carriers import (
    DIRECT_FETCH_METHODS,
    Carrier,
    CarrierPage,
    resolve_carriers,
)
from app.ingest.fetch import FetchResult
from app.models.scrape_run import ScrapeRun

logger = get_logger(__name__)

METHOD = "browser"

#: Per-page ceiling. Generous, because these are heavy marketing pages on
#: origins that are already suspicious of us -- but finite, because a page that
#: hangs is the TK failure mode and `timeout` is the outcome that records it.
PAGE_TIMEOUT_MS = 30_000
VIEWPORT = {"width": 1440, "height": 900}
#: Courtesy pause between page loads, jittered. Sequential by construction:
#: eight carriers hitting eight origins in parallel would be faster and would
#: also be the traffic shape every bot detector is tuned for.
DELAY_RANGE_S = (2.0, 4.0)
#: The same courtesy, scaled to what a JSON request costs the other end. These
#: are single API calls to three unrelated origins, not page loads with fifty
#: sub-resources each.
DIRECT_DELAY_RANGE_S = (0.5, 1.5)

#: A body this short is not a campaign page. A challenge interstitial, an empty
#: JS shell or an error stub all land here, and all of them mean "we did not
#: read the page" rather than "the carrier has no campaigns".
MIN_BODY_CHARS = 200

#: Lowercased substrings that mean a wall answered instead of the site. Kept
#: short and unambiguous on purpose: a false positive here demotes a carrier
#: that was actually working.
CHALLENGE_MARKERS: tuple[str, ...] = (
    "access denied",
    "verify you are human",
    "are you a human",
    "checking your browser",
    "cloudflare",
    "captcha",
    "unusual traffic",
    "request blocked",
    "erişim engellendi",
    "robot olmadığınızı",
)

#: HTTP statuses that are a wall rather than a broken page. 403/429 are the
#: documented QR/EK answers; 5xx is what emirates.com returns to a non-browser.
_BLOCKED_STATUSES = frozenset({401, 403, 405, 407, 429})

#: net::ERR_* strings that mean the origin refused us at the transport layer --
#: the TK/AJet signature. A wall, not a bug in this code.
_BLOCKED_ERROR_MARKERS: tuple[str, ...] = (
    "err_connection_reset",
    "err_connection_refused",
    "err_connection_closed",
    "err_empty_response",
    "err_http2_protocol_error",
    "err_ssl",
    "err_too_many_redirects",
)

_WHITESPACE = re.compile(r"\s+")

#: Default per-run ceiling on extraction calls. The Groq free tier is a shared
#: product-wide budget (~260 calls/day already committed), and a first run
#: where every page's hash is "changed" would spend one of these per LLM-backed
#: page in a single sweep. Ten is above the steady-state need -- and the need
#: shrank at round 9, because AJet and SQ moved to the structured path and now
#: cost nothing from this budget at all, leaving five LLM-backed pages (TK's
#: one, QR's two, EY's one, EK's one, BA's one).
DEFAULT_MAX_LLM_CALLS = 10


@dataclass
class ExtractionBudget:
    """How many LLM calls this sweep may still spend, and what it did.

    Mutable and passed down rather than returned up, because the cap has to
    hold across carriers: eight carriers each allowed ten calls is not a cap
    of ten.
    """

    remaining: int = DEFAULT_MAX_LLM_CALLS
    spent: int = 0
    capped_pages: int = 0
    inserted: int = 0
    updated: int = 0
    merged: int = 0
    dropped: int = 0
    failed_pages: int = 0

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def as_summary(self) -> dict:
        return {
            "llm_calls": self.spent,
            "campaigns_inserted": self.inserted,
            "campaigns_updated": self.updated,
            "campaigns_merged": self.merged,
            "campaigns_dropped": self.dropped,
            "extraction_capped": self.capped_pages,
            "extraction_failed": self.failed_pages,
        }


@dataclass(frozen=True)
class ExtractionOutcome:
    """Whether this page's content may be baselined, and why not if not."""

    accounted_for: bool
    note: str | None = None


# `FetchResult` used to be defined here. It moved to app/ingest/fetch.py when
# the impersonated GET and the JSON API paths started producing one too: it is
# the shared currency of all three fetch methods now, not just the browser's.
# It is imported (not re-declared) above, so `from app.ingest.deep_scan import
# FetchResult` still resolves and this module's classifier still owns what a
# result *means*.


def normalize(raw: str | None) -> str:
    """Collapse a page's text to the form that gets hashed.

    Whitespace only: no lowercasing, no punctuation stripping. A campaign page
    reflowing at a different viewport width, or a build putting its blocks on
    one line instead of twelve, must not read as a new campaign -- but "%30" is
    not "%40" and case is how carriers write their promo codes.
    """
    if not raw:
        return ""
    return _WHITESPACE.sub(" ", raw).strip()


def content_hash(normalized: str) -> str:
    """sha256 of the normalised text. The value stored in `content_hash`."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_challenge(normalized: str) -> str | None:
    """The reason this text is a wall, or None if it looks like a real page."""
    if len(normalized) < MIN_BODY_CHARS:
        return f"Gövde çok kısa ({len(normalized)} karakter) — sayfa okunamadı."
    lowered = normalized.casefold()
    for marker in CHALLENGE_MARKERS:
        if marker in lowered:
            return f"Bot duvarı işareti: “{marker}”."
    return None


def is_timeout_error(exc: BaseException) -> bool:
    """True for Playwright's TimeoutError -- without importing Playwright.

    Matched on the class name because this has to hold in an environment where
    playwright is not installed (the module-level import is lazy for exactly
    that reason). `playwright.async_api.TimeoutError`, `asyncio.TimeoutError`
    and the builtin all mean the same thing to `outcome`.
    """
    return isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError"


def classify_outcome(fetch: FetchResult) -> tuple[str, str | None]:
    """(outcome, error) for one page attempt -- the whole failure taxonomy.

    Ordered by how much each signal is trusted. A timeout is unambiguous. A
    status code is next, and a blocking status stays `blocked` even if a body
    came with it -- while a 4xx below that band is a wrong URL, not a wall, and
    has to stay distinguishable from one. Then a transport-level refusal with
    no response at all. Only last does the text get a say, because a bot wall
    answers 200 with a body and the status code alone would call it success.
    """
    if fetch.timed_out:
        return "timeout", fetch.error or "Sayfa süre aşımına uğradı."

    status = fetch.http_status
    if status is not None and (status in _BLOCKED_STATUSES or status >= 500):
        return "blocked", f"HTTP {status}"
    if status is not None and 400 <= status < 500:
        # 404/410: the URL is wrong, not walled. Distinct on purpose -- it is
        # how a best-known URL in carriers.py gets corrected.
        return "parse_error", f"HTTP {status}"

    if fetch.error and fetch.text is None:
        # No response object at all: the origin refused us before HTTP started,
        # which for TK and AJet is the wall itself rather than a broken URL.
        lowered = fetch.error.casefold()
        if any(marker in lowered for marker in _BLOCKED_ERROR_MARKERS):
            return "blocked", fetch.error
        return "parse_error", fetch.error

    normalized = normalize(fetch.text)
    if not normalized:
        return "parse_error", fetch.error or "Sayfadan hiç metin çıkarılamadı."

    challenge = detect_challenge(normalized)
    if challenge is not None:
        return "blocked", challenge

    return "ok", None


async def latest_ok_hash(db: AsyncSession, url: str) -> str | None:
    """The hash from the last run of this URL that actually read the page.

    Compared against the successful runs only: a blocked run carries no hash,
    and comparing against a failed one would report every recovery as a change.
    """
    return (
        await db.execute(
            select(ScrapeRun.content_hash)
            .where(
                ScrapeRun.url == url,
                ScrapeRun.outcome == "ok",
                ScrapeRun.content_hash.is_not(None),
            )
            .order_by(ScrapeRun.started_at.desc().nullslast())
            .limit(1)
        )
    ).scalar_one_or_none()


def decide_changed(previous: str | None, current: str | None) -> bool | None:
    """Tri-state, matching the column's documented meaning.

    NULL when the run produced no hash at all (blocked, timed out, unreadable)
    -- "we do not know" is not "unchanged". True for a first ever successful
    read: the extraction step reads ok+changed rows, and a page nobody has ever
    read is entirely new work even though there is nothing to diff it against.
    """
    if current is None:
        return None
    if previous is None:
        return True
    return previous != current


async def record_run(
    db: AsyncSession,
    *,
    carrier_code: str,
    url: str,
    started_at: datetime,
    finished_at: datetime,
    outcome: str,
    http_status: int | None = None,
    hash_value: str | None = None,
    changed: bool | None = None,
    error: str | None = None,
    method: str = METHOD,
) -> ScrapeRun:
    """Write one attempt to the run log. Flushed, not committed: the caller
    commits once per scan so a crash mid-sweep leaves no half-written history."""
    run = ScrapeRun(
        carrier_code=carrier_code,
        url=url[:500],
        method=method,
        started_at=started_at,
        finished_at=finished_at,
        outcome=outcome,
        http_status=http_status,
        content_hash=hash_value,
        changed=changed,
        # Truncated: some of these are stack-trace-length, and the useful part
        # of a net::ERR_ message is always at the front.
        error=error[:2000] if error else None,
    )
    db.add(run)
    await db.flush()
    return run


async def _fetch_page(context, carrier_page: CarrierPage) -> FetchResult:
    """Load one page in an already-open browser context and return its text.

    Never raises: every failure mode of someone else's website is a
    `FetchResult` that `classify_outcome` turns into a row. A carrier that
    hangs must not cost the six other carriers their run.
    """
    page = await context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT_MS)
    try:
        response = await page.goto(
            carrier_page.url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT_MS,
        )
        status = response.status if response is not None else None

        if carrier_page.wait_for:
            try:
                await page.wait_for_selector(
                    carrier_page.wait_for, timeout=PAGE_TIMEOUT_MS
                )
            except Exception as exc:  # noqa: BLE001 -- see below
                # The page loaded but never rendered its campaign list. Read it
                # anyway: the body text is what decides whether this was a wall
                # (blocked) or a markup change (parse_error), and throwing the
                # body away here would erase that distinction.
                logger.info(
                    "deep_scan_wait_for_missed",
                    url=carrier_page.url,
                    selector=carrier_page.wait_for,
                    error=str(exc)[:200],
                )

        if carrier_page.block_selector:
            blocks = await page.locator(carrier_page.block_selector).all_inner_texts()
            text = "\n".join(blocks)
            if not text.strip():
                # Selector found nothing -- fall back to the body so the
                # classifier can tell a wall from a renamed CSS class.
                text = await page.inner_text("body")
        else:
            text = await page.inner_text("body")

        return FetchResult(text=text, http_status=status)
    except Exception as exc:  # noqa: BLE001 -- every failure becomes a row
        return FetchResult(
            text=None,
            error=f"{type(exc).__name__}: {exc}",
            timed_out=is_timeout_error(exc),
        )
    finally:
        await page.close()


async def extract_changed_page(
    db: AsyncSession,
    *,
    carrier: Carrier,
    carrier_page: CarrierPage,
    text: str,
    hash_value: str,
    budget: ExtractionBudget,
    now: datetime,
    today: date,
) -> ExtractionOutcome:
    """Run the extraction chain over the text this scan just read.

    The text is passed in, not re-fetched: within one run the page is already
    in memory, and spending a second page load on an origin that is only
    tolerating the first one would be both slower and ruder.

    Returns whether this page's content may be baselined. Anything short of a
    completed extraction -- capped, failed, no model configured -- comes back
    `accounted_for=False`, which is what keeps the page queued for the next
    run. A page the model read and found no campaigns on IS accounted for: the
    answer "there are no campaigns here" is a real answer, and re-asking it
    twice a day forever would spend the budget on it.
    """
    if budget.exhausted:
        budget.capped_pages += 1
        logger.info(
            "deep_scan_extraction_capped", carrier=carrier.code, url=carrier_page.url
        )
        return ExtractionOutcome(False, "extraction_capped")

    from app.pipeline.campaign_extract import extract_campaigns_from_page, persist_extracted

    budget.remaining -= 1
    result = await extract_campaigns_from_page(
        text,
        carrier=carrier,
        page_url=carrier_page.url,
        source_quality=carrier.source_quality,
        detected_at=now,
        today=today,
        content_hash=hash_value,
    )
    budget.spent += result.llm_calls
    budget.dropped += len(result.dropped)

    if not result.succeeded:
        budget.failed_pages += 1
        return ExtractionOutcome(False, f"extraction_failed:{result.reason}")

    for extracted in result.campaigns:
        written = await persist_extracted(db, extracted)
        if written == "inserted":
            budget.inserted += 1
        elif written == "merged":
            budget.merged += 1
        else:
            budget.updated += 1
    return ExtractionOutcome(True)


async def extract_structured_entries(
    db: AsyncSession,
    *,
    carrier: Carrier,
    page_url: str,
    entries,
    hash_value: str,
    budget: ExtractionBudget,
    now: datetime,
    today: date,
    source_name: str,
) -> ExtractionOutcome:
    """Persist a structured carrier feed's campaigns. No LLM call, no budget.

    The counterpart to `extract_changed_page` for the two carriers that publish
    JSON (app/ingest/ajet_campaigns.py, app/ingest/sq_campaigns.py). It shares
    that function's counters and its return type so `deep_scan`'s summary and
    hash-withholding logic do not need to know which path produced a row -- but
    it does not touch `budget.remaining`, because there is nothing to ration:
    the work is a dictionary lookup and a date regex, and it costs the shared
    Groq tier exactly nothing.

    Always `accounted_for=True` when it runs at all. A deterministic mapping
    has no partial failure mode: it either produced the campaigns the feed
    stated, or the harvest never got a readable body and `classify_outcome`
    already recorded that as a failed fetch.
    """
    from app.pipeline.campaign_extract import build_structured_campaign, persist_extracted

    for entry in entries:
        extracted, drop_reason = build_structured_campaign(
            entry,
            carrier=carrier,
            detected_at=now,
            today=today,
            source_name=source_name,
            source_quality=carrier.source_quality,
            content_hash=hash_value,
        )
        if extracted is None:
            budget.dropped += 1
            logger.info(
                "deep_scan_structured_rejected",
                carrier=carrier.code,
                campaign=entry.campaign_name,
                reason=drop_reason,
            )
            continue

        written = await persist_extracted(db, extracted)
        if written == "inserted":
            budget.inserted += 1
        elif written == "merged":
            budget.merged += 1
        else:
            budget.updated += 1

    return ExtractionOutcome(True)


async def _record_attempt(
    db: AsyncSession,
    carrier: Carrier,
    carrier_page: CarrierPage,
    fetch: FetchResult,
    summary: dict,
    *,
    started_at: datetime,
    method: str,
    budget: ExtractionBudget | None,
    extraction_enabled: bool,
    structured_entries=None,
    structured_source_name: str | None = None,
) -> None:
    """Everything between a fetch and its `scrape_runs` row.

    Split out of the browser scan when the impersonated and JSON paths started
    producing `FetchResult`s too. Classification, hashing, change detection,
    extraction hand-off and the run log are identical for all three methods --
    only the way the bytes were obtained differs -- so this is the one place
    that decides what a fetch meant, and adding a fourth fetch method adds no
    branch here.

    `structured_entries` is the fork: when a carrier's feed already carries
    parsed campaigns, they are persisted directly; when it does not, the page
    text goes to the LLM chain under the shared call budget.
    """
    outcome, error = classify_outcome(fetch)

    normalized = ""
    hash_value = None
    if outcome == "ok":
        normalized = normalize(fetch.text)
        hash_value = content_hash(normalized)
    run_url = carrier_page.fetch_url
    previous = await latest_ok_hash(db, run_url) if hash_value else None
    changed = decide_changed(previous, hash_value)

    recorded_hash = hash_value
    if changed and extraction_enabled and budget is not None:
        if structured_entries is not None:
            extraction = await extract_structured_entries(
                db,
                carrier=carrier,
                page_url=carrier_page.url,
                entries=structured_entries,
                hash_value=hash_value,
                budget=budget,
                now=started_at,
                today=started_at.date(),
                source_name=structured_source_name or f"{carrier.display_name} kampanya sayfası",
            )
        else:
            extraction = await extract_changed_page(
                db,
                carrier=carrier,
                carrier_page=carrier_page,
                text=normalized,
                hash_value=hash_value,
                budget=budget,
                now=started_at,
                today=started_at.date(),
            )
        if not extraction.accounted_for:
            # Withhold the hash so the next run still sees this page as
            # changed -- see the module docstring. The row stays `ok` and
            # `changed`: the fetch genuinely succeeded, and pretending
            # otherwise would corrupt the bot-wall telemetry to carry an
            # extraction fact.
            recorded_hash = None
            error = extraction.note

    finished_at = datetime.now(timezone.utc)
    await record_run(
        db,
        carrier_code=carrier.code,
        url=run_url,
        started_at=started_at,
        finished_at=finished_at,
        outcome=outcome,
        http_status=fetch.http_status,
        hash_value=recorded_hash,
        changed=changed,
        error=error,
        method=method,
    )

    summary["scanned"] += 1
    if outcome == "blocked":
        summary["blocked"] += 1
    elif outcome in ("timeout", "parse_error"):
        summary["errors"] += 1
    if changed:
        summary["changed"] += 1

    logger.info(
        "deep_scan_page",
        carrier=carrier.code,
        url=run_url,
        method=method,
        kind=carrier_page.kind,
        outcome=outcome,
        changed=changed,
        http_status=fetch.http_status,
        elapsed_ms=int((finished_at - started_at).total_seconds() * 1000),
        error=error,
    )


async def _scan_carrier_page(
    db: AsyncSession,
    context,
    carrier: Carrier,
    carrier_page: CarrierPage,
    summary: dict,
    dry_run: bool,
    *,
    budget: ExtractionBudget | None = None,
    extraction_enabled: bool = False,
) -> None:
    started_at = datetime.now(timezone.utc)
    fetch = await _fetch_page(context, carrier_page)
    await _record_attempt(
        db,
        carrier,
        carrier_page,
        fetch,
        summary,
        started_at=started_at,
        method=METHOD,
        budget=budget,
        extraction_enabled=extraction_enabled,
    )


# --- the browserless carriers ------------------------------------------------
#
# A table, not a branch. carriers.py's promise is that adding a carrier is
# adding a registry entry, and the two carriers whose campaigns arrive as JSON
# genuinely do need code of their own -- an endpoint shape is not something a
# URL can describe. So the code they need is named here, once, keyed by the
# carrier it belongs to, and the scan loop below stays free of `if code ==`.
#
# Every handler returns the same triple: the `FetchResult` the classifier
# reads, the structured campaigns (empty when the carrier's page has to go
# through the LLM chain), and the source name for provenance rows.


@dataclass(frozen=True)
class DirectHarvest:
    fetch: FetchResult
    entries: tuple = ()
    source_name: str | None = None

    @property
    def is_structured(self) -> bool:
        return bool(self.entries)


async def _harvest_tk(carrier_page: CarrierPage) -> DirectHarvest:
    from app.ingest.tk_campaigns import SOURCE_NAME, fetch_campaign_page

    return DirectHarvest(
        fetch=await fetch_campaign_page(carrier_page.url), source_name=SOURCE_NAME
    )


async def _harvest_ajet(carrier_page: CarrierPage) -> DirectHarvest:
    from app.ingest.ajet_campaigns import SOURCE_NAME, harvest

    result = await harvest(carrier_page.url)
    return DirectHarvest(fetch=result.fetch, entries=result.entries, source_name=SOURCE_NAME)


async def _harvest_sq(carrier_page: CarrierPage) -> DirectHarvest:
    from app.ingest.sq_campaigns import SOURCE_NAME, harvest

    result = await harvest(carrier_page.fetch_url)
    return DirectHarvest(fetch=result.fetch, entries=result.entries, source_name=SOURCE_NAME)


DIRECT_HARVESTERS = {
    "TK": _harvest_tk,
    "VF": _harvest_ajet,
    "SQ": _harvest_sq,
}


async def _scan_direct_carriers(
    db: AsyncSession,
    carriers: list[Carrier],
    summary: dict,
    *,
    budget: ExtractionBudget,
    extraction_enabled: bool,
) -> None:
    """The httpx/curl_cffi carriers, before any browser is launched.

    First for two reasons. They are the cheapest requests in the sweep -- one
    HTTP round trip each, no Chromium, and for AJet and SQ no LLM call either
    -- so a runner that cannot install a browser, or a Chromium that wedges,
    still leaves this product with three carriers' campaigns. And the courtesy
    pause between them is smaller than the browser loop's for the same reason
    the browser loop has one: three JSON requests to three unrelated origins is
    not a traffic shape anything is tuned to notice.
    """
    for carrier in carriers:
        handler = DIRECT_HARVESTERS.get(carrier.code)
        if handler is None:
            # A registry entry declaring a direct method with nothing to fetch
            # it. Logged rather than raised: one misconfigured carrier must not
            # cost the sweep, and the missing row is the signal.
            logger.warning(
                "deep_scan_no_direct_handler",
                carrier=carrier.code,
                method=carrier.fetch_method,
            )
            continue

        for carrier_page in carrier.pages:
            started_at = datetime.now(timezone.utc)
            try:
                harvested = await handler(carrier_page)
            except Exception as exc:  # noqa: BLE001 -- every failure becomes a row
                harvested = DirectHarvest(
                    fetch=FetchResult(text=None, error=f"{type(exc).__name__}: {exc}")
                )
            await _record_attempt(
                db,
                carrier,
                carrier_page,
                harvested.fetch,
                summary,
                started_at=started_at,
                method=carrier.fetch_method,
                budget=budget,
                extraction_enabled=extraction_enabled,
                structured_entries=harvested.entries if harvested.is_structured else None,
                structured_source_name=harvested.source_name,
            )
            await asyncio.sleep(random.uniform(*DIRECT_DELAY_RANGE_S))


async def deep_scan(
    db: AsyncSession,
    *,
    carriers: list[str] | None = None,
    dry_run: bool = False,
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
) -> dict:
    """Read every non-static carrier's campaign source, record what happened,
    and extract the campaigns off the ones that changed.

    Two phases. The browserless carriers (`api`, `impersonate`) go first and
    commit before Chromium is even imported; the browser carriers follow. Only
    the LLM-backed pages draw on `max_llm_calls` -- AJet's and SQ's structured
    feeds cost nothing from that budget, which is most of why they were worth
    finding.

    Returns counters, but the real output is two-fold: `scrape_runs` carries
    the per-carrier ok/blocked telemetry the carrier list is maintained from,
    and `promotions` carries whatever the extraction chain could verify.

    `dry_run` suppresses extraction and nothing else -- the run log is written
    either way, which is what makes the bot-wall go/no-go gate readable. So
    does an unset `CAMPAIGN_V2_ENABLED`: with the flag off this is exactly the
    telemetry-only sweep that shipped before the chain existed.

    `max_llm_calls` caps extraction for the whole sweep, not per carrier. Pages
    that hit the cap keep their previous baseline and are picked up by the next
    run (see the module docstring), so the cap defers work rather than
    discarding it.
    """
    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "skipped_static": 0}

    from app.core.config import get_settings

    extraction_enabled = get_settings().campaign_v2_enabled and not dry_run
    budget = ExtractionBudget(remaining=max(0, max_llm_calls))
    summary.update(budget.as_summary())

    selected = resolve_carriers(carriers)
    direct = [c for c in selected if c.fetch_method in DIRECT_FETCH_METHODS]
    targets = [c for c in selected if c.fetch_method == "browser"]
    # Pegasus is read by app/ingest/promo_scrape.py with a parser tuned to its
    # markup; loading it again here would be duplicate traffic for worse data.
    summary["skipped_static"] = len([c for c in selected if c.fetch_method == "static"])

    # Cheapest first, and unconditionally: these need neither Chromium nor (for
    # the two JSON carriers) a model, so a runner with no browser still comes
    # back with campaigns.
    if direct:
        await _scan_direct_carriers(
            db, direct, summary, budget=budget, extraction_enabled=extraction_enabled
        )
        summary.update(budget.as_summary())
        await db.commit()

    if not targets:
        logger.info("deep_scan_no_browser_carriers", requested=carriers)
        logger.info(
            "deep_scan_complete", dry_run=dry_run, extraction=extraction_enabled, **summary
        )
        return summary

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        # Same contract as app/pdf/render.py: no browser here is a no-op, not a
        # crash. This job only ever runs on the Actions runner that installs
        # requirements-dev.txt + `playwright install chromium`.
        logger.warning("deep_scan_skipped_playwright_not_installed")
        return summary

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            first = True
            for carrier in targets:
                # A context per carrier: fresh cookie jar between airlines, and
                # the locale each one serves its campaigns in.
                context = await browser.new_context(
                    viewport=VIEWPORT,
                    locale=carrier.language,
                )
                try:
                    for carrier_page in carrier.pages:
                        if not first:
                            await asyncio.sleep(random.uniform(*DELAY_RANGE_S))
                        first = False
                        await _scan_carrier_page(
                            db,
                            context,
                            carrier,
                            carrier_page,
                            summary,
                            dry_run,
                            budget=budget,
                            extraction_enabled=extraction_enabled,
                        )
                finally:
                    await context.close()
        finally:
            await browser.close()

    summary.update(budget.as_summary())
    await db.commit()
    logger.info(
        "deep_scan_complete", dry_run=dry_run, extraction=extraction_enabled, **summary
    )
    return summary
