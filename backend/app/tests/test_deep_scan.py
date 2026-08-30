"""Deep-scan tests: everything except the browser.

No live Chromium and no network here on purpose. CI has no route to any of
these carriers' origins (that is the whole reason this module exists), so a
test that drove a real browser would be a test of GitHub's egress, and it would
be red for reasons that have nothing to do with this code. What is testable --
and what actually decides whether an LLM call gets spent -- is the half between
the fetch and the row: normalisation, hashing, outcome classification and
change detection. `app.ingest.deep_scan.FetchResult` is the seam that lets
those run without playwright installed at all.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.ingest import deep_scan as deep_scan_module
from app.ingest.carriers import (
    CARRIER_MASTER,
    FETCH_METHODS,
    PAGE_KINDS,
    browser_carriers,
    direct_carriers,
    resolve_carriers,
)
from app.ingest.deep_scan import (
    FetchResult,
    classify_outcome,
    content_hash,
    decide_changed,
    detect_challenge,
    is_timeout_error,
    latest_ok_hash,
    normalize,
    record_run,
)
from app.llm.gazetteer import AIRLINE_ALIASES
from app.models.scrape_run import ScrapeRun

NOW = datetime(2026, 8, 28, 5, 0, tzinfo=timezone.utc)

CAMPAIGN_TEXT = (
    "Yurt içi uçuşlarda %30 indirim. Satış dönemi 1 Eylül 2026 - 15 Eylül 2026. "
    "Seyahat dönemi 1 Ekim 2026 - 30 Kasım 2026. Kampanya koşulları geçerlidir. "
    "Promosyon kodu: SONBAHAR30. Sınırlı sayıda koltuk için geçerlidir ve "
    "belirtilen tarihler dışındaki uçuşlarda kullanılamaz."
)


# --- normalisation + hashing ---------------------------------------------


def test_whitespace_reflow_is_not_a_campaign_change():
    """The same campaign rendered at a different viewport, or by a build that
    minifies differently, must not spend an LLM call."""
    spaced_out = "  Yurt içi uçuşlarda\n\n\t%30   indirim.  \n"
    single_line = "Yurt içi uçuşlarda %30 indirim."

    assert normalize(spaced_out) == single_line
    assert content_hash(normalize(spaced_out)) == content_hash(normalize(single_line))


def test_a_changed_discount_is_a_changed_hash():
    """And normalisation stops short of anything that could erase this: %30 and
    %40 are different campaigns, and so are different promo codes."""
    assert content_hash(normalize("%30 indirim")) != content_hash(normalize("%40 indirim"))
    assert content_hash(normalize("kod: YAZ30")) != content_hash(normalize("kod: YAZ40"))


def test_normalize_handles_nothing_at_all():
    assert normalize(None) == ""
    assert normalize("   \n  ") == ""


def test_the_hash_is_sha256_hex():
    """String(64) in the schema; a shorter digest would be silently truncated."""
    assert len(content_hash(normalize(CAMPAIGN_TEXT))) == 64


# --- challenge detection --------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Access Denied. You do not have permission to access this page.",
        "Please verify you are human before continuing to the offers page.",
        "Checking your browser before accessing the site. Cloudflare Ray ID: 8f2",
        "Erişim engellendi. Lütfen daha sonra tekrar deneyin.",
    ],
)
def test_a_wall_is_recognised_from_its_text(body):
    # Padded past MIN_BODY_CHARS so the marker, not the length, is what fires.
    padded = body + " " + "lorem ipsum dolor sit amet " * 12
    assert detect_challenge(normalize(padded)) is not None


def test_a_near_empty_body_is_a_wall_not_an_empty_campaign_list():
    """A JS shell that rendered nothing looks exactly like a carrier with no
    campaigns, and treating it as the latter would report a real campaign list
    disappearing."""
    assert detect_challenge(normalize("<noscript>Enable JavaScript</noscript>")) is not None


def test_a_real_campaign_page_is_not_a_wall():
    assert detect_challenge(normalize(CAMPAIGN_TEXT)) is None


# --- outcome classification ----------------------------------------------


def test_a_403_is_blocked():
    outcome, error = classify_outcome(
        FetchResult(text=CAMPAIGN_TEXT, http_status=403)
    )
    assert outcome == "blocked"
    assert "403" in error


def test_a_503_is_blocked_which_is_what_emirates_answers():
    outcome, _ = classify_outcome(FetchResult(text=None, http_status=503, error="boom"))
    assert outcome == "blocked"


def test_a_429_is_blocked():
    assert classify_outcome(FetchResult(text=CAMPAIGN_TEXT, http_status=429))[0] == "blocked"


def test_a_200_with_a_challenge_body_is_blocked():
    """The reason http_status is not the outcome: a bot wall answers 200."""
    wall = "Verify you are human. " + "This page cannot be displayed. " * 12
    outcome, error = classify_outcome(FetchResult(text=wall, http_status=200))
    assert outcome == "blocked"
    assert "verify you are human" in error


def test_a_timeout_is_a_timeout():
    outcome, error = classify_outcome(
        FetchResult(text=None, error="Timeout 30000ms exceeded.", timed_out=True)
    )
    assert outcome == "timeout"
    assert "30000" in error


def test_a_playwright_timeout_error_is_recognised_without_importing_playwright():
    """`is_timeout_error` matches on the class name so it holds in an
    environment with no browser installed -- which is this one."""

    class TimeoutError(Exception):  # shadows the builtin, exactly as playwright's does
        pass

    assert is_timeout_error(TimeoutError("Timeout 30000ms exceeded")) is True
    assert is_timeout_error(ValueError("nope")) is False


def test_a_connection_reset_is_a_wall_not_a_bug():
    """TK and AJet reset the stream rather than answering; that is a block, and
    filing it as an error would hide the carrier's real status."""
    outcome, _ = classify_outcome(
        FetchResult(text=None, error="Error: net::ERR_CONNECTION_RESET at https://tk")
    )
    assert outcome == "blocked"


def test_a_404_is_a_parse_error_not_a_block():
    """How a best-known URL in carriers.py gets corrected: a wrong path must be
    distinguishable from a walled one."""
    outcome, error = classify_outcome(FetchResult(text="Not found", http_status=404))
    assert outcome == "parse_error"
    assert "404" in error


def test_a_page_that_yielded_no_text_is_a_parse_error():
    outcome, _ = classify_outcome(FetchResult(text="   ", http_status=200))
    assert outcome == "parse_error"


def test_a_real_page_is_ok():
    outcome, error = classify_outcome(FetchResult(text=CAMPAIGN_TEXT, http_status=200))
    assert outcome == "ok"
    assert error is None


# --- change detection -----------------------------------------------------


def test_changed_is_null_when_there_is_no_hash_to_compare():
    """Matching the column's documented meaning: a blocked run does not know
    whether the page changed, which is not the same as unchanged."""
    assert decide_changed("a" * 64, None) is None


def test_a_first_ever_successful_read_counts_as_changed():
    """PR4 extracts ok+changed rows. A page nobody has ever read is entirely
    new work, even though there is nothing to diff it against."""
    assert decide_changed(None, "a" * 64) is True


def test_same_hash_is_unchanged_and_a_different_one_is_changed():
    assert decide_changed("a" * 64, "a" * 64) is False
    assert decide_changed("a" * 64, "b" * 64) is True


URL = "https://www.turkishairlines.com/tr-tr/ucus-firsatlari/"


async def test_change_detection_against_a_previous_ok_run(db_session):
    unchanged_hash = content_hash(normalize(CAMPAIGN_TEXT))
    await record_run(
        db_session,
        carrier_code="TK",
        url=URL,
        started_at=NOW - timedelta(hours=10),
        finished_at=NOW - timedelta(hours=10) + timedelta(seconds=8),
        outcome="ok",
        http_status=200,
        hash_value=unchanged_hash,
        changed=True,
    )
    await db_session.commit()

    previous = await latest_ok_hash(db_session, URL)
    assert previous == unchanged_hash
    assert decide_changed(previous, unchanged_hash) is False

    moved = content_hash(normalize(CAMPAIGN_TEXT.replace("%30", "%40")))
    assert decide_changed(previous, moved) is True


async def test_a_blocked_run_does_not_become_the_comparison_baseline(db_session):
    """Otherwise the first successful read after a wall lifts would compare
    against nothing and every recovery would look like a change... and worse, a
    hash-less blocked row would be picked as `latest` and read as NULL."""
    baseline = content_hash(normalize(CAMPAIGN_TEXT))
    await record_run(
        db_session,
        carrier_code="TK",
        url=URL,
        started_at=NOW - timedelta(days=1),
        finished_at=NOW - timedelta(days=1),
        outcome="ok",
        http_status=200,
        hash_value=baseline,
        changed=True,
    )
    await record_run(
        db_session,
        carrier_code="TK",
        url=URL,
        started_at=NOW,
        finished_at=NOW,
        outcome="blocked",
        http_status=200,
        error="Bot duvarı",
    )
    await db_session.commit()

    assert await latest_ok_hash(db_session, URL) == baseline


async def test_the_baseline_is_per_url_not_per_carrier(db_session):
    """TK has two campaign pages. They change independently, and sharing one
    baseline between them would make each one report the other's changes."""
    other = "https://www.turkishairlines.com/tr-tr/kampanyalar/"
    await record_run(
        db_session,
        carrier_code="TK",
        url=URL,
        started_at=NOW,
        finished_at=NOW,
        outcome="ok",
        hash_value="a" * 64,
        changed=True,
    )
    await db_session.commit()

    assert await latest_ok_hash(db_session, other) is None


async def test_a_recorded_run_carries_the_telemetry_the_gate_is_read_from(db_session):
    await record_run(
        db_session,
        carrier_code="EK",
        url="https://www.emirates.com/tr/english/special-offers/",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=12),
        outcome="blocked",
        http_status=503,
        error="HTTP 503",
    )
    await db_session.commit()

    run = (
        await db_session.execute(select(ScrapeRun).where(ScrapeRun.carrier_code == "EK"))
    ).scalar_one()
    assert run.method == "browser"
    assert run.outcome == "blocked"
    assert run.http_status == 503
    assert run.content_hash is None
    assert run.changed is None


async def test_a_very_long_error_is_truncated_rather_than_failing_the_insert(db_session):
    await record_run(
        db_session,
        carrier_code="QR",
        url="https://www.qatarairways.com/en-us/offers.html",
        started_at=NOW,
        finished_at=NOW,
        outcome="parse_error",
        error="x" * 5000,
    )
    await db_session.commit()

    run = (
        await db_session.execute(select(ScrapeRun).where(ScrapeRun.carrier_code == "QR"))
    ).scalar_one()
    assert len(run.error) == 2000


async def test_the_method_column_holds_the_name_of_every_fetch_method(db_session):
    """The regression the first Azure run of this sweep found. `impersonate` is
    eleven characters and the column was ten wide, so the row recording TK's
    first successful fetch is what killed the run."""
    for index, method in enumerate(sorted(FETCH_METHODS)):
        await record_run(
            db_session,
            carrier_code="TK",
            url=f"https://www.turkishairlines.com/tr-tr/kampanyalar/?{index}",
            started_at=NOW,
            finished_at=NOW,
            outcome="ok",
            method=method,
        )
    await db_session.commit()

    runs = (await db_session.execute(select(ScrapeRun))).scalars().all()
    assert {run.method for run in runs} == set(FETCH_METHODS)


# --- one unwritable row is not a dead sweep -------------------------------


async def test_a_row_that_cannot_be_written_does_not_cost_the_other_carriers(
    db_session, monkeypatch
):
    """The shape of the Azure failure, reproduced against a real database.

    Not a raised Python exception -- a rejected INSERT, which is the harder
    case: it aborts the Postgres transaction, so without a savepoint every
    later carrier's write would fail too, on an error none of them caused. TK
    here is unwritable; AJet and SQ must still come back with rows, and the
    sweep must still commit.
    """
    from app.ingest.deep_scan import DirectHarvest, ExtractionBudget, _scan_direct_carriers

    monkeypatch.setattr(deep_scan_module, "DIRECT_DELAY_RANGE_S", (0.0, 0.0))

    async def harvest(_carrier_page) -> DirectHarvest:
        return DirectHarvest(fetch=FetchResult(text=CAMPAIGN_TEXT, http_status=200))

    monkeypatch.setattr(
        deep_scan_module,
        "DIRECT_HARVESTERS",
        {code: harvest for code in ("TK", "VF", "SQ")},
    )

    real_record_run = deep_scan_module.record_run

    async def record(db, **kwargs):
        if kwargs["carrier_code"] == "TK":
            # Longer than the column is wide, whatever that width is: the point
            # is a database refusing the row, not this particular overflow.
            kwargs["method"] = "impersonate" * 4
        return await real_record_run(db, **kwargs)

    monkeypatch.setattr(deep_scan_module, "record_run", record)

    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "record_errors": 0}
    carriers = [CARRIER_MASTER[code] for code in ("TK", "VF", "SQ")]
    await _scan_direct_carriers(
        db_session,
        carriers,
        summary,
        budget=ExtractionBudget(remaining=0),
        extraction_enabled=False,
    )
    await db_session.commit()

    assert summary["record_errors"] == 1, "the unwritable page is counted, not raised"
    assert summary["scanned"] == 2, "the two carriers after it still ran"

    runs = (await db_session.execute(select(ScrapeRun))).scalars().all()
    assert sorted(run.carrier_code for run in runs) == ["SQ", "VF"]
    assert all(run.outcome == "ok" for run in runs)


async def test_a_failing_record_leaves_the_session_usable_for_the_next_page(
    db_session, monkeypatch
):
    """The same guard against a plain exception -- a bug in our own code on the
    way to the row, rather than the database refusing it."""
    from app.ingest.deep_scan import DirectHarvest, ExtractionBudget, _scan_direct_carriers

    monkeypatch.setattr(deep_scan_module, "DIRECT_DELAY_RANGE_S", (0.0, 0.0))

    async def harvest(_carrier_page) -> DirectHarvest:
        return DirectHarvest(fetch=FetchResult(text=CAMPAIGN_TEXT, http_status=200))

    monkeypatch.setattr(
        deep_scan_module, "DIRECT_HARVESTERS", {code: harvest for code in ("TK", "VF")}
    )

    real_record_run = deep_scan_module.record_run

    async def record(db, **kwargs):
        if kwargs["carrier_code"] == "TK":
            raise RuntimeError("kayıt yazılamadı")
        return await real_record_run(db, **kwargs)

    monkeypatch.setattr(deep_scan_module, "record_run", record)

    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "record_errors": 0}
    await _scan_direct_carriers(
        db_session,
        [CARRIER_MASTER[code] for code in ("TK", "VF")],
        summary,
        budget=ExtractionBudget(remaining=0),
        extraction_enabled=False,
    )
    await db_session.commit()

    assert summary["record_errors"] == 1
    runs = (await db_session.execute(select(ScrapeRun))).scalars().all()
    assert [run.carrier_code for run in runs] == ["VF"]


# --- carrier registry -----------------------------------------------------


def test_every_registry_entry_is_well_formed():
    assert CARRIER_MASTER, "the registry is the config; an empty one is a bug"
    for code, carrier in CARRIER_MASTER.items():
        assert carrier.code == code, "keyed by its own code, so lookups cannot drift"
        assert carrier.fetch_method in FETCH_METHODS
        assert 0.0 < carrier.source_quality <= 1.0
        assert len(carrier.language) == 2
        assert carrier.pages, f"{code} has nowhere to be fetched from"
        for page in carrier.pages:
            assert page.kind in PAGE_KINDS
            assert page.url.startswith("https://")
            assert len(page.url) <= 500, "scrape_runs.url is String(500)"


def test_every_carrier_resolves_to_the_same_airline_the_gazetteer_knows():
    """A carrier scanned here and a carrier named in an article have to be one
    entity, or the campaign timeline shows the same airline twice."""
    for carrier in CARRIER_MASTER.values():
        assert carrier.alias in AIRLINE_ALIASES, carrier.alias
        assert AIRLINE_ALIASES[carrier.alias][1] == carrier.code


def test_the_fetch_method_split_deep_scan_depends_on():
    """Pegasus is promo_scrape's; three carriers are reachable without a
    browser; only the four that render their offers client-side need one.

    Written as an exact partition rather than a membership check: moving a
    carrier between methods changes what the sweep costs and what it can still
    do when Chromium is unavailable, so it should never happen silently."""
    assert CARRIER_MASTER["PC"].fetch_method == "static"

    assert {c.code for c in direct_carriers()} == {"TK", "VF", "SQ"}
    browsers = browser_carriers()
    assert {c.code for c in browsers} == {"QR", "EK", "EY", "BA"}
    for carrier in browsers + direct_carriers():
        assert any(page.kind == "campaign" for page in carrier.pages)


def test_every_direct_carrier_has_something_to_fetch_it_with():
    """`_scan_direct_carriers` looks the handler up by code rather than
    branching on it, so a registry entry with no handler is a carrier that
    silently scans nothing."""
    from app.ingest.deep_scan import DIRECT_HARVESTERS

    assert {c.code for c in direct_carriers()} == set(DIRECT_HARVESTERS)


def test_an_api_carrier_records_the_endpoint_it_actually_fetched():
    """AJet's campaigns come from a CMS gateway on another host. Change
    detection has to key on what was requested, not on the page a human would
    open, or the run log would claim we read a DataDome-walled page."""
    page = CARRIER_MASTER["VF"].pages[0]
    assert page.url.startswith("https://www.ajet.com/tr/kesfet/kampanyalar/")
    assert page.fetch_url.startswith("https://gatewaycmsint.cloud.ajet.com/")
    # And a page with no separate endpoint fetches itself.
    assert CARRIER_MASTER["TK"].pages[0].fetch_url == CARRIER_MASTER["TK"].pages[0].url


def test_no_two_carriers_claim_the_same_url():
    """Change detection keys on the URL, so a URL in two carriers' page lists
    would give each of them the other's baseline."""
    urls = [page.url for carrier in CARRIER_MASTER.values() for page in carrier.pages]
    assert len(urls) == len(set(urls))


def test_carriers_resolve_by_code_or_by_the_name_a_human_would_type():
    """`--carriers ajet` has to find VF: the brand and the IATA code diverge for
    exactly the carrier most likely to be typed by hand."""
    assert [c.code for c in resolve_carriers(["ajet"])] == ["VF"]
    assert [c.code for c in resolve_carriers(["tk", " VF "])] == ["TK", "VF"]
    assert [c.code for c in resolve_carriers(["TK", "TK"])] == ["TK"]
    assert len(resolve_carriers(None)) == len(CARRIER_MASTER)


def test_an_unknown_carrier_is_refused_rather_than_silently_scanning_nothing():
    with pytest.raises(ValueError, match="XX"):
        resolve_carriers(["TK", "XX"])


# --- CLI wiring -----------------------------------------------------------


def test_the_cli_parses_the_deep_scan_flags():
    """Cheap guard on the one thing the workflow's dispatch inputs depend on."""
    import sys
    from unittest.mock import patch

    from app import cli

    with patch.object(
        sys, "argv", ["cli", "deep-scan", "--carriers", "TK,VF", "--dry-run"]
    ), patch.object(cli.asyncio, "run") as run:
        cli.main()

    assert run.call_count == 1
    # Closed rather than awaited: asyncio.run is stubbed, so the coroutine the
    # dispatch built would otherwise be garbage-collected un-awaited.
    run.call_args[0][0].close()
