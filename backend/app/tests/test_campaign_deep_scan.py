"""The deep-scan extraction hook, against a real database and a canned model.

What is tested here is the *hand-off*, not the chain (that is
test_campaign_extract.py) and not the browser (that is test_deep_scan.py, which
explains why CI never drives one): a changed page becomes rows, an unchanged
one costs nothing, and -- the case that actually needed designing -- a page
whose extraction did not happen must not be marked as read.

The fixture dates sit in 2099 on purpose. `_scan_carrier_page` stamps its own
`datetime.now()` as the scan time, because that is what a scan time is, and the
rule layer rejects a campaign whose booking window closed a week ago. A fixture
dated this year would therefore start failing on a date nobody chose.
"""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.ingest import deep_scan as deep_scan_module
from app.ingest.carriers import CARRIER_MASTER
from app.ingest.deep_scan import (
    ExtractionBudget,
    FetchResult,
    _scan_carrier_page,
    content_hash,
    deep_scan,
    normalize,
    record_run,
)
from app.models.promotion import Promotion
from app.models.scrape_run import ScrapeRun

EK = CARRIER_MASTER["EK"]
PAGE = EK.pages[0]

PAGE_TEXT = (
    "Autumn fares to Europe. Save up to 30% on Economy Class fares from DXB to LHR. "
    "Book by 15 September 2099. Travel between 1 October 2099 and 30 November 2099. "
    "Book now on emirates.com. "
    "Dubai to Istanbul offer. Return fares from 1200 AED. Book by 20 September 2099."
)
CHANGED_PAGE_TEXT = PAGE_TEXT.replace("30%", "40%")

EUROPE = {
    "campaign_name": "Autumn fares to Europe",
    "campaign_type": "SEASONAL_PROMOTION",
    "is_fare_campaign": True,
    "booking_end": "2099-09-15",
    "travel_start": "2099-10-01",
    "travel_end": "2099-11-30",
    "discount_pct": 30,
    "origin": "DXB",
    "destination": "LHR",
    "source_text": {
        "booking_end": "Book by 15 September 2099.",
        "travel_start": "Travel between 1 October 2099 and 30 November 2099.",
        "travel_end": "Travel between 1 October 2099 and 30 November 2099.",
        "discount_pct": "Save up to 30% on Economy Class fares",
        "origin": "from DXB to LHR",
        "destination": "from DXB to LHR",
    },
}

ISTANBUL = {
    "campaign_name": "Dubai to Istanbul offer",
    "campaign_type": "DESTINATION_PROMOTION",
    "is_fare_campaign": True,
    "booking_end": "2099-09-20",
    "price_floor": 1200,
    "currency": "AED",
    "origin": "Dubai",
    "destination": "Istanbul",
    "source_text": {
        "booking_end": "Book by 20 September 2099",
        "price_floor": "Return fares from 1200 AED",
        "origin": "Dubai to Istanbul offer",
        "destination": "Dubai to Istanbul offer",
    },
}

BOTH = {"campaigns": [EUROPE, ISTANBUL]}


@pytest.fixture
def canned(monkeypatch):
    """Point the chain's model at a dict this test controls.

    `set(payload)` swaps the answer mid-test, which is how the "the page
    changed" cases are written.
    """
    state = {"payload": BOTH}

    async def generate(_prompt: str) -> str:
        payload = state["payload"]
        return payload if isinstance(payload, str) else json.dumps(payload)

    monkeypatch.setattr("app.llm.factory.get_raw_generator", lambda: generate)
    return state


def _serve(monkeypatch, text: str) -> None:
    async def fake_fetch(_context, _carrier_page) -> FetchResult:
        return FetchResult(text=text, http_status=200)

    monkeypatch.setattr(deep_scan_module, "_fetch_page", fake_fetch)


async def _scan(db, monkeypatch, *, text=PAGE_TEXT, budget=None, enabled=True, dry_run=False):
    _serve(monkeypatch, text)
    budget = budget or ExtractionBudget(remaining=5)
    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "skipped_static": 0}
    await _scan_carrier_page(
        db, None, EK, PAGE, summary, dry_run, budget=budget, extraction_enabled=enabled
    )
    await db.commit()
    return budget, summary


async def _promotions(db) -> list[Promotion]:
    rows = (await db.execute(select(Promotion).order_by(Promotion.url))).scalars().all()
    return list(rows)


async def _runs(db) -> list[ScrapeRun]:
    rows = (
        await db.execute(select(ScrapeRun).order_by(ScrapeRun.started_at))
    ).scalars().all()
    return list(rows)


# --- the happy path -------------------------------------------------------


async def test_a_changed_page_becomes_one_row_per_campaign(db_session, canned, monkeypatch):
    budget, summary = await _scan(db_session, monkeypatch)

    rows = await _promotions(db_session)
    assert len(rows) == 2, "two campaigns on one page are two rows"
    assert len({row.url for row in rows}) == 2, "promotions.url is UNIQUE"
    assert all(row.url.startswith(PAGE.url + "#") for row in rows)
    assert budget.spent == 1, "one page, one LLM call"
    assert summary["changed"] == 1

    europe = next(row for row in rows if "autumn" in row.url)
    assert europe.airline_code == "EK"
    assert europe.campaign_type == "SEASONAL_PROMOTION"
    assert europe.business_class == "ACTIVE_CAMPAIGN"
    assert europe.ond == "DXB-LHR"
    assert europe.route_scope == "OND"
    assert europe.discount_pct == 30
    assert europe.evidence_json["booking_end"]["source_text"].startswith("Book by")
    assert europe.classification_reason
    assert europe.content_hash == content_hash(normalize(PAGE_TEXT))
    assert europe.first_seen_at is not None and europe.last_seen_at is not None
    assert europe.raw_text


async def test_a_read_page_is_baselined_so_the_next_run_is_free(
    db_session, canned, monkeypatch
):
    await _scan(db_session, monkeypatch)
    budget, summary = await _scan(db_session, monkeypatch)

    assert summary["changed"] == 0, "same text, same hash"
    assert budget.spent == 0, "an unchanged page must never cost an LLM call"
    assert len(await _promotions(db_session)) == 2, "and must not duplicate its rows"


async def test_the_same_campaign_with_new_terms_refreshes_its_row(
    db_session, canned, monkeypatch
):
    """The carrier raised the discount. That is the same campaign at the same
    URL fragment -- one row, updated, not a second row alongside it."""
    await _scan(db_session, monkeypatch)

    canned["payload"] = {"campaigns": [{**EUROPE, "discount_pct": 40,
                                        "source_text": {**EUROPE["source_text"],
                                                        "discount_pct": "Save up to 40%"}},
                                       ISTANBUL]}
    budget, summary = await _scan(db_session, monkeypatch, text=CHANGED_PAGE_TEXT)

    rows = await _promotions(db_session)
    assert summary["changed"] == 1
    assert len(rows) == 2
    europe = next(row for row in rows if "autumn" in row.url)
    assert europe.discount_pct == 40
    assert budget.updated == 2


# --- carry-over: the case the design turns on -----------------------------


async def test_a_capped_page_keeps_its_old_baseline_and_is_extracted_next_run(
    db_session, canned, monkeypatch
):
    """The bug this prevents: the scan records the new hash, extraction never
    runs because the budget is spent, and every later run sees "unchanged" --
    so those campaigns are never read at all, forever."""
    await record_run(
        db_session,
        carrier_code="EK",
        url=PAGE.url,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        outcome="ok",
        http_status=200,
        hash_value="b" * 64,
        changed=True,
    )
    await db_session.commit()

    budget, summary = await _scan(
        db_session, monkeypatch, budget=ExtractionBudget(remaining=0)
    )

    assert summary["changed"] == 1
    assert budget.capped_pages == 1
    assert await _promotions(db_session) == []

    capped = (await _runs(db_session))[-1]
    assert capped.outcome == "ok", "the fetch really did succeed"
    assert capped.changed is True
    assert capped.content_hash is None, "withheld: this page has not been dealt with"
    assert capped.error == "extraction_capped"

    # Next run, budget restored: the page is still a change against the old
    # baseline, so the campaigns finally land.
    budget, summary = await _scan(db_session, monkeypatch)
    assert summary["changed"] == 1
    assert len(await _promotions(db_session)) == 2
    assert (await _runs(db_session))[-1].content_hash == content_hash(normalize(PAGE_TEXT))


async def test_a_failed_extraction_queues_the_page_rather_than_swallowing_it(
    db_session, canned, monkeypatch
):
    canned["payload"] = "Sorry, I cannot help with that."
    budget, _summary = await _scan(db_session, monkeypatch)

    assert budget.failed_pages == 1
    assert await _promotions(db_session) == []
    run = (await _runs(db_session))[-1]
    assert run.content_hash is None
    assert run.error.startswith("extraction_failed:schema_error")

    canned["payload"] = BOTH
    await _scan(db_session, monkeypatch)
    assert len(await _promotions(db_session)) == 2


async def test_a_page_with_no_campaigns_is_baselined_not_re_asked_forever(
    db_session, canned, monkeypatch
):
    """"There are no campaigns here" is a real answer. Withholding the hash for
    it would spend a call on the same empty page twice a day indefinitely."""
    canned["payload"] = {"campaigns": []}
    await _scan(db_session, monkeypatch)

    run = (await _runs(db_session))[-1]
    assert run.content_hash == content_hash(normalize(PAGE_TEXT))
    assert run.error is None

    budget, summary = await _scan(db_session, monkeypatch)
    assert summary["changed"] == 0
    assert budget.spent == 0


# --- dedup on the way in ---------------------------------------------------


async def test_a_campaign_already_written_from_a_news_article_is_merged_not_doubled(
    db_session, canned, monkeypatch
):
    """The other half of the same campaign: promo_dedup is asked before every
    insert, and the carrier's own page outranks the report about it."""
    now = datetime.now(timezone.utc)
    seeded = Promotion(
        airline_code="EK",
        airline_name="Emirates",
        title_tr="Autumn fares to Europe",
        summary_tr="Emirates Avrupa uçuşlarında indirim açıkladı.",
        url="https://havayolu101.example/emirates-autumn-fares",
        source_name="Havayolu 101",
        detected_at=now - timedelta(days=1),
    )
    db_session.add(seeded)
    await db_session.commit()
    seeded_id = seeded.id

    await _scan(db_session, monkeypatch)

    rows = await _promotions(db_session)
    assert len(rows) == 2, "the news row absorbed one campaign; only the other is new"

    merged = next(row for row in rows if row.title_tr == "Autumn fares to Europe")
    assert merged.id == seeded_id, "the incumbent row survived; nothing was re-inserted"
    # The airline's own page wins the fields it is authoritative about -- its
    # URL, its dates, its rate -- and the richer summary wins on length, which
    # is promo_dedup's merge direction, not a new policy.
    assert merged.url.startswith(PAGE.url + "#")
    assert merged.source_name == "Emirates kampanya sayfası"
    assert "son rezervasyon tarihi" in merged.summary_tr
    assert merged.sale_ends is not None, "the page's dates reached the surviving row"
    assert merged.detected_at.date() == (now - timedelta(days=1)).date(), (
        "the earliest sighting wins: the Yeni badge must not re-fire"
    )
    assert merged.business_class == "ACTIVE_CAMPAIGN"
    assert merged.route_scope == "OND"


# --- the flag and the dry run ---------------------------------------------


async def test_with_extraction_off_the_scan_is_exactly_the_telemetry_sweep(
    db_session, canned, monkeypatch
):
    """Flag off (or --dry-run): hashes recorded, nothing extracted, no LLM
    call -- the behaviour the bot-wall go/no-go dispatch was read from."""
    budget, summary = await _scan(db_session, monkeypatch, enabled=False)

    assert summary["changed"] == 1
    assert budget.spent == 0
    assert await _promotions(db_session) == []
    run = (await _runs(db_session))[-1]
    assert run.content_hash == content_hash(normalize(PAGE_TEXT))
    assert run.error is None


async def test_the_budget_is_a_sweep_wide_cap_not_a_per_page_one(
    db_session, canned, monkeypatch
):
    budget = ExtractionBudget(remaining=1)
    await _scan(db_session, monkeypatch, budget=budget)

    other_page = replace(PAGE, url=PAGE.url + "europe/")
    _serve(monkeypatch, PAGE_TEXT)
    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "skipped_static": 0}
    await _scan_carrier_page(
        db_session, None, EK, other_page, summary, False, budget=budget, extraction_enabled=True
    )
    await db_session.commit()

    assert budget.spent == 1
    assert budget.capped_pages == 1


async def test_the_summary_reports_extraction_even_when_nothing_was_scanned(db_session):
    """`deep_scan` returns early for a static-only selection; the counters the
    workflow prints have to exist on that path too."""
    summary = await deep_scan(db_session, carriers=["PC"], max_llm_calls=3)

    assert summary["skipped_static"] == 1
    assert summary["llm_calls"] == 0
    assert summary["campaigns_inserted"] == 0
    assert summary["extraction_capped"] == 0
