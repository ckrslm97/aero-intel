"""Campaign detection and the campaign timeline's API.

Two things here can quietly ruin the feature, and neither is caught by
"does it return rows".

The first is the heuristic extractor *inventing* a date. Every date column on
`promotions` is nullable precisely because press coverage of a campaign is
routinely vague, and the timeline draws a guessed date exactly like a
published one -- so an over-eager regex is an unrecoverable error, not a
cosmetic one. Most of these tests therefore assert on what stays `None`.

The second is the API's date filters, all three branches of which exist only
to survive those nulls: a dated window filters on its real edges, an
open-ended one is still running and must reach any `date_from`, and one with
no start date at all is a point marker filtered on `detected_at`.
"""
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi import Response
from sqlalchemy import select

from app.api.v1.promotions import count_new_promotions, list_promotions
from app.core.tr_dates import format_optional_range
from app.ingest import promo_scrape
from app.ingest.carriers import CARRIER_MASTER
from app.ingest.promo_scrape import SOURCE_NAME as SCRAPE_SOURCE
from app.ingest.promo_scrape import ScrapedPromo, scrape_promotions
from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import NEW_WINDOW_HOURS, Promotion
from app.pipeline.promo_dedup import (
    MAX_DETECTION_GAP,
    PromoCandidate,
    dedupe_existing_promotions,
    find_duplicate,
    is_duplicate,
    merge_candidate,
    title_similarity,
    tr_normalize,
)
from app.pipeline.promotions import (
    TRACKED_AIRLINES,
    heuristic_extract,
    parse_llm_payload,
)
from app.taxonomy import RIVAL_CODES

NOW = datetime.now(timezone.utc)


# --- heuristic fallback -------------------------------------------------


def test_reads_a_percentage_written_the_turkish_way():
    fields = heuristic_extract("Pegasus'tan %40'a varan indirim", "")
    assert fields.discount_pct == 40


def test_reads_a_percentage_written_the_english_way():
    fields = heuristic_extract("Up to 25% off", "")
    assert fields.discount_pct == 25


@pytest.mark.parametrize("text", ["%0 indirim", "%250 uçuş", "PC 1904 sefer"])
def test_rejects_a_percentage_that_cannot_be_a_discount(text):
    # 0 is not a discount and a three-digit match is a price or a flight
    # number that picked up a stray %.
    assert heuristic_extract(text, "").discount_pct is None


def test_reads_an_explicit_sale_range():
    fields = heuristic_extract(
        "THY kampanyası",
        "Satış dönemi 15 Ekim 2026 - 30 Kasım 2026 tarihleri arasındadır.",
    )
    assert fields.sale_starts == date(2026, 10, 15)
    assert fields.sale_ends == date(2026, 11, 30)
    # Nothing in the text is about flying, so the travel window stays unknown.
    assert fields.travel_starts is None
    assert fields.travel_ends is None


def test_a_travel_cue_files_the_range_under_travel_not_sale():
    fields = heuristic_extract(
        "AJet fırsatı",
        "Seyahat tarihleri 01.06.2027 ile 30.09.2027 arasında geçerlidir.",
    )
    assert fields.travel_starts == date(2027, 6, 1)
    assert fields.travel_ends == date(2027, 9, 30)
    assert fields.sale_starts is None


def test_a_deadline_is_an_end_date_not_a_start():
    # The single most common shape in campaign copy. Reading "30 Kasım'a
    # kadar" as a start would draw the bar in entirely the wrong place.
    fields = heuristic_extract(
        "Son fırsat", "Biletlerinizi 30 Kasım 2026'a kadar satın alabilirsiniz."
    )
    assert fields.sale_ends == date(2026, 11, 30)
    assert fields.sale_starts is None


def test_a_start_cue_is_a_start_date():
    fields = heuristic_extract(
        "Yeni kampanya", "Bilet satışı 2 Mayıs 2026 itibaren başlıyor."
    )
    assert fields.sale_starts == date(2026, 5, 2)
    assert fields.sale_ends is None


def test_prose_with_no_dates_yields_no_dates():
    fields = heuristic_extract(
        "Emirates'ten yaz kampanyası",
        "Havayolu bu yaz boyunca cazip fiyatlar sunacağını duyurdu.",
    )
    assert (
        fields.sale_starts,
        fields.sale_ends,
        fields.travel_starts,
        fields.travel_ends,
    ) == (None, None, None, None)


def test_a_yearless_date_is_dropped_unless_the_article_supplies_a_year():
    body = "Satış 15 Ekim'e kadar sürecek."
    assert heuristic_extract("x", body).sale_ends is None
    # The article's own publication year is the only reading that isn't a guess.
    assert heuristic_extract("x", body, default_year=2026).sale_ends == date(2026, 10, 15)


def test_two_far_apart_dates_are_not_paired_into_a_range():
    fields = heuristic_extract(
        "Kampanya",
        "Satışlar 1 Mart 2026 tarihinde başladı. " + "Ayrıntılar için sayfayı ziyaret edin. " * 3
        + "Ayrıca 1 Haziran 2026 tarihinde bir basın toplantısı yapılacak.",
    )
    # Whatever else it reads, it must not claim a Mart->Haziran sale window
    # out of two dates that are a paragraph apart.
    assert not (fields.sale_starts == date(2026, 3, 1) and fields.sale_ends == date(2026, 6, 1))


def test_markets_mix_region_slugs_and_city_names():
    fields = heuristic_extract(
        "Kampanya", "Avrupa ve Orta Doğu hatlarında, Londra ve Dubai dahil."
    )
    assert fields.markets is not None
    parts = fields.markets.split(",")
    assert "europe" in parts
    assert "middle-east" in parts
    assert "londra" in parts


def test_no_recognisable_market_leaves_the_field_null():
    # The drawer renders this as "Kapsam: kaynakta belirtilmemiş" rather than
    # inventing a scope.
    assert heuristic_extract("Kampanya", "Tüm hatlarda geçerli.").markets is None


# --- LLM payload parsing (the path the heuristic backs up) ---------------


def test_llm_payload_survives_a_fenced_response():
    fields = parse_llm_payload(
        '```json\n{"discount_pct": 30, "sale_starts": "2026-05-02", '
        '"sale_ends": null, "markets": ["europe", "londra"]}\n```'
    )
    assert fields is not None
    assert fields.discount_pct == 30
    assert fields.sale_starts == date(2026, 5, 2)
    assert fields.sale_ends is None
    assert fields.markets == "europe,londra"


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2, 3]", "{oops"])
def test_unusable_llm_output_falls_through_rather_than_writing_an_empty_row(raw):
    assert parse_llm_payload(raw) is None


def test_every_scanned_carrier_can_be_drawn():
    # This used to be a hand-copied literal, and it is why Singapore Airlines
    # shipped as the bare string "SQ" in the default accent colour: SQ was added
    # to the carrier master, started producing campaigns, and the literal still
    # said ten. Asserting the relation instead of the list means the next
    # carrier added to CARRIER_MASTER fails here until it has a lane -- and,
    # because nav.ts is generated from this same set, a brand hex too.
    missing = set(CARRIER_MASTER) - set(TRACKED_AIRLINES)
    assert not missing, (
        f"carriers scanned but not drawable: {sorted(missing)} -- a campaign by one "
        "has no lane, no brand colour and no logo on the timeline"
    )


def test_rivals_are_carriers_we_can_draw():
    # The Gazete's "Ana Rakipler" chip row is airlineTabs filtered by these, so
    # a rival with no brand entry would simply vanish from the row.
    assert set(RIVAL_CODES) <= set(TRACKED_AIRLINES)


# --- Turkish range formatting ------------------------------------------


def test_a_half_known_window_says_which_half_is_missing():
    assert format_optional_range(date(2026, 5, 2), date(2026, 11, 30)) == (
        "2 Mayıs - 30 Kasım 2026"
    )
    assert format_optional_range(date(2026, 5, 2), None) == "2 Mayıs 2026 — bitiş belirtilmedi"
    assert format_optional_range(None, date(2026, 11, 30)) == (
        "başlangıç belirtilmedi — 30 Kasım 2026"
    )
    assert format_optional_range(None, None) == "Belirtilmedi"


def test_a_window_crossing_new_year_states_both_years():
    # Live flypgs data: "15 Ekim 2024 / 31 Ağustos 2026". Printing only the end
    # year would render a two-year partnership as a ten-month window running
    # backwards through the calendar.
    assert format_optional_range(date(2024, 10, 15), date(2026, 8, 31)) == (
        "15 Ekim 2024 - 31 Ağustos 2026"
    )


# --- API filters --------------------------------------------------------


async def _promo(db, *, slug: str, airline: str = "PC", **kwargs) -> Promotion:
    row = Promotion(
        airline_code=airline,
        airline_name=TRACKED_AIRLINES[airline],
        title_tr=slug,
        summary_tr="",
        url=f"https://example.com/{slug}",
        source_name="test",
        detected_at=kwargs.pop("detected_at", NOW),
        **kwargs,
    )
    db.add(row)
    await db.flush()
    return row


async def _list(db, **kwargs):
    return await list_promotions(
        airline=kwargs.pop("airline", None),
        date_from=kwargs.pop("date_from", None),
        date_to=kwargs.pop("date_to", None),
        days=kwargs.pop("days", None),
        response=Response(),
        db=db,
    )


async def test_dated_window_is_filtered_on_its_real_edges(db_session):
    await _promo(
        db_session,
        slug="spring",
        sale_starts=date(2026, 3, 1),
        sale_ends=date(2026, 3, 31),
    )
    assert len(await _list(db_session, date_from=date(2026, 3, 15))) == 1
    # Ends before the window opens.
    assert await _list(db_session, date_from=date(2026, 4, 1)) == []
    # Starts after the window closes.
    assert await _list(db_session, date_to=date(2026, 2, 1)) == []


async def test_an_open_ended_campaign_reaches_any_later_date(db_session):
    # No end date means nobody has said it stopped, so it is still running and
    # must not vanish from a window that opens after it started.
    await _promo(db_session, slug="open", sale_starts=date(2026, 3, 1), sale_ends=None)
    rows = await _list(db_session, date_from=date(2027, 1, 1))
    assert len(rows) == 1
    assert rows[0].sale_range_tr.endswith("bitiş belirtilmedi")


async def test_a_campaign_with_no_start_date_is_filtered_on_detection(db_session):
    # These render as a point marker at detected_at, so that is the only date
    # the filter can honestly use.
    detected = datetime(2026, 6, 10, tzinfo=timezone.utc)
    await _promo(db_session, slug="pointy", detected_at=detected)

    assert len(await _list(db_session, date_from=date(2026, 6, 1))) == 1
    assert await _list(db_session, date_from=date(2026, 7, 1)) == []
    assert len(await _list(db_session, date_to=date(2026, 6, 30))) == 1
    assert await _list(db_session, date_to=date(2026, 5, 31)) == []


async def test_days_filters_on_detection_not_on_the_sale_window(db_session):
    # A campaign detected today whose sale window is next year is still "new".
    await _promo(
        db_session,
        slug="future",
        sale_starts=date(2027, 5, 1),
        sale_ends=date(2027, 6, 1),
        detected_at=NOW,
    )
    await _promo(db_session, slug="stale", detected_at=NOW - timedelta(days=30))

    rows = await _list(db_session, days=7)
    assert [r.title_tr for r in rows] == ["future"]


async def test_airline_filter_is_multi_select(db_session):
    await _promo(db_session, slug="pc", airline="PC")
    await _promo(db_session, slug="tk", airline="TK")
    await _promo(db_session, slug="lh", airline="LH")

    assert len(await _list(db_session, airline=["PC", "TK"])) == 2
    # Absent means every carrier, not none.
    assert len(await _list(db_session)) == 3


async def test_rows_come_back_newest_sighting_first(db_session):
    await _promo(db_session, slug="older", detected_at=NOW - timedelta(days=2))
    await _promo(db_session, slug="newer", detected_at=NOW)

    assert [r.title_tr for r in await _list(db_session)] == ["newer", "older"]


async def test_computed_turkish_ranges_ride_along_with_every_row(db_session):
    await _promo(
        db_session,
        slug="both",
        sale_starts=date(2026, 5, 2),
        sale_ends=date(2026, 11, 30),
        travel_starts=date(2026, 6, 1),
        travel_ends=None,
    )
    row = (await _list(db_session))[0]
    assert row.sale_range_tr == "2 Mayıs - 30 Kasım 2026"
    assert row.travel_range_tr == "1 Haziran 2026 — bitiş belirtilmedi"


async def test_new_count_covers_the_whole_table_not_a_view_window(db_session):
    await _promo(db_session, slug="fresh-pc", airline="PC", detected_at=NOW)
    await _promo(
        db_session,
        slug="fresh-tk",
        airline="TK",
        detected_at=NOW - timedelta(hours=NEW_WINDOW_HOURS - 1),
    )
    await _promo(
        db_session,
        slug="old",
        airline="LH",
        detected_at=NOW - timedelta(hours=NEW_WINDOW_HOURS + 1),
    )

    payload = await count_new_promotions(response=Response(), db=db_session)
    assert payload["window_hours"] == NEW_WINDOW_HOURS
    assert payload["count"] == 2
    assert payload["airline_codes"] == ["PC", "TK"]


# --- contract: no publish endpoint serves a below-threshold or dead row -
#
# Faz 15's contract-test requirement. Neither endpoint used to filter on
# `confidence_band`/`superseded_at` at all, so once pipeline_v2 starts writing
# these columns, a low-confidence campaign (or one Faz 13's
# `mark_legacy_campaigns_superseded()` retired) would still have shown up
# here. `confidence_band IS NULL` has to stay visible: it is not "assessed
# and found wanting", it is "never assessed" -- the state of every row
# `promo_scrape.py` has ever written -- and the fix must not use a bare
# `!= "low"`, which SQL's three-valued logic would silently apply to NULLs
# too.


async def test_low_confidence_promotion_is_not_listed(db_session):
    await _promo(db_session, slug="shown", confidence_band="high")
    await _promo(db_session, slug="hidden", confidence_band="low")

    assert [r.title_tr for r in await _list(db_session)] == ["shown"]


async def test_superseded_promotion_is_not_listed(db_session):
    await _promo(db_session, slug="live")
    await _promo(db_session, slug="retired", superseded_at=NOW)

    assert [r.title_tr for r in await _list(db_session)] == ["live"]


async def test_null_confidence_promotion_still_shows_because_it_was_never_assessed(
    db_session,
):
    # Every currently-live scraped Pegasus row has confidence_band IS NULL --
    # promo_scrape.py never sets it. Treating "never assessed" the same as
    # "assessed and found wanting" would empty the live page.
    await _promo(db_session, slug="never-assessed", confidence_band=None)

    assert [r.title_tr for r in await _list(db_session)] == ["never-assessed"]


async def test_new_count_excludes_low_confidence_and_superseded_rows(db_session):
    await _promo(db_session, slug="counted", airline="PC", detected_at=NOW)
    await _promo(
        db_session, slug="low", airline="TK", detected_at=NOW, confidence_band="low"
    )
    await _promo(
        db_session,
        slug="retired",
        airline="LH",
        detected_at=NOW,
        superseded_at=NOW,
    )

    payload = await count_new_promotions(response=Response(), db=db_session)
    assert payload["count"] == 1
    assert payload["airline_codes"] == ["PC"]


async def test_url_is_the_idempotency_key(db_session):
    await _promo(db_session, slug="same")
    stored = (await db_session.execute(select(Promotion))).scalars().all()
    assert len(stored) == 1
    assert stored[0].url == "https://example.com/same"


# --- one campaign, two detection paths ----------------------------------
#
# The third thing that can quietly ruin the feature, and the one these cover:
# the same real campaign arriving twice. `promotions.url` is unique, but the
# airline's own campaign page and a news report about that campaign are two
# different URLs, so the key does not see them as one -- live, Pegasus's "Kuzey
# Kıbrıs %40" was drawn on the timeline as a dated bar AND a dateless point
# marker at once.
#
# The risk runs the other way too, and harder: a false merge silently deletes a
# competitor's campaign from the timeline, with nothing left on screen to
# notice. So there are as many tests below for what must NOT merge as for what
# must, and the "must not" cases are taken verbatim from the live table.


async def _stored(db, **fields) -> Promotion:
    row = Promotion(
        airline_code=fields.pop("airline_code", "PC"),
        airline_name=fields.pop("airline_name", "Pegasus Airlines"),
        summary_tr=fields.pop("summary_tr", ""),
        source_name=fields.pop("source_name", "Haber"),
        detected_at=fields.pop("detected_at", NOW),
        **fields,
    )
    db.add(row)
    await db.flush()
    return row


def _candidate(**fields) -> PromoCandidate:
    base = {
        "airline_code": "PC",
        "airline_name": "Pegasus Airlines",
        "summary_tr": "",
        "source_name": SCRAPE_SOURCE,
        "detected_at": NOW,
    }
    base.update(fields)
    return PromoCandidate(**base)


# --- Turkish normalization (the trap this whole matcher rests on) --------


def test_turkish_casing_folds_the_way_turkish_does():
    # The trap: Python lowercases "İ" to "i" plus a combining dot, and "I" to a
    # dotted "i". Neither is Turkish, and both break a naive title match.
    assert "İNDİRİM".lower() != "indirim"
    assert tr_normalize("İNDİRİM") == "indirim"
    assert tr_normalize("KIBRIS") == "kibris"
    # Case endings hang off an apostrophe in Turkish and differ between two
    # tellings of one campaign, so they are stripped rather than compared.
    assert tr_normalize("Kıbrıs'a") == "kibris"
    assert tr_normalize("Pegasus'tan %40'a varan") == "pegasus 40 varan"


def test_the_same_title_in_two_casings_is_the_same_title():
    assert title_similarity(
        "KUZEY KIBRIS UÇUŞLARINDA %40 İNDİRİM",
        "Kuzey Kıbrıs uçuşlarında %40 indirim",
    ) == 1.0


# --- what must merge ----------------------------------------------------


async def test_a_campaign_found_by_both_paths_ends_up_as_one_row(db_session, monkeypatch):
    """The live defect, end to end through the scraper.

    A news report reached us first (no dates, good prose); the airline's own
    page then serves the same campaign under a different URL with a real sale
    window. One campaign must mean one row.
    """
    news = await _stored(
        db_session,
        title_tr="Pegasus'tan Kuzey Kıbrıs uçuşlarında %40 indirim",
        summary_tr="Pegasus, Kuzey Kıbrıs uçuşlarında salı-perşembe günleri %40 indirim uyguluyor.",
        discount_pct=40,
        url="https://haber.example.com/pegasus-kktc-indirim",
        source_name="Haber",
        detected_at=NOW - timedelta(days=3),
    )
    scraped = ScrapedPromo(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        summary_tr="Salı, çarşamba ve perşembe günleri geçerlidir.",
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-40-indirimli-2026",
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
        discount_pct=40,
    )

    async def _fake_fetch(_client):
        return [scraped]

    monkeypatch.setattr(promo_scrape, "fetch_pegasus", _fake_fetch)
    async with httpx.AsyncClient() as client:
        result = await scrape_promotions(db_session, client=client)

    assert (result["merged"], result["inserted"]) == (1, 0)
    rows = (await db_session.execute(select(Promotion))).scalars().all()
    assert len(rows) == 1
    survivor = rows[0]
    assert survivor.id == news.id
    # The airline is authoritative about its own sale window and its own link.
    assert (survivor.sale_starts, survivor.sale_ends) == (date(2026, 8, 21), date(2026, 8, 23))
    assert survivor.url == scraped.url
    assert survivor.source_name == SCRAPE_SOURCE
    # ...but not about how well the campaign is explained.
    assert survivor.summary_tr == news.summary_tr
    # Earliest sighting: this campaign is three days old, not new. Adopting the
    # scrape's timestamp would flash it as "Yeni" all over again.
    assert survivor.detected_at == NOW - timedelta(days=3)

    # The report that found it first is not discarded by being taken over: both
    # pages stay on file, which is what a corroboration count counts.
    sources = (
        await db_session.execute(
            select(CampaignSource).order_by(CampaignSource.url)
        )
    ).scalars().all()
    assert [(s.url, s.source_tier) for s in sources] == [
        ("https://haber.example.com/pegasus-kktc-indirim", "secondary"),
        (scraped.url, "official"),
    ]
    # ...and what the takeover changed is written down rather than overwritten.
    versions = (await db_session.execute(select(CampaignVersion))).scalars().all()
    assert len(versions) == 1
    assert versions[0].version_no == 1
    assert versions[0].changed_fields["sale_ends"] == {
        "previous": None, "new": "2026-08-23"
    }
    assert survivor.last_changed_at is not None


async def test_a_freshly_scraped_campaign_files_the_page_and_versions_nothing(
    db_session, monkeypatch
):
    """Creation is not a change: what it was before is nothing. The page it was
    read from is recorded from the start, so no campaign is ever in the table
    without a source."""
    scraped = ScrapedPromo(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs Uçuşları %40 indirimli!",
        summary_tr="Salı, çarşamba ve perşembe günleri geçerlidir.",
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kktc-2026",
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
        discount_pct=40,
    )

    async def _fake_fetch(_client):
        return [scraped]

    monkeypatch.setattr(promo_scrape, "fetch_pegasus", _fake_fetch)
    async with httpx.AsyncClient() as client:
        assert (await scrape_promotions(db_session, client=client))["inserted"] == 1

    row = (await db_session.execute(select(Promotion))).scalars().one()
    source = (await db_session.execute(select(CampaignSource))).scalars().one()
    assert (source.promotion_id, source.url) == (row.id, scraped.url)
    assert source.source_tier == "official"
    assert row.first_seen_at is not None and row.last_seen_at is not None
    assert (await db_session.execute(select(CampaignVersion))).scalars().all() == []


async def test_a_campaign_the_carrier_extended_in_place_is_versioned(
    db_session, monkeypatch
):
    """Pegasus extends campaigns without changing their URL, so the row is
    overwritten in place -- the case where "never overwrite silently" is the
    whole requirement. Re-scraping the same page unchanged writes nothing."""
    url = "https://www.flypgs.com/kampanyali-ucak-biletleri/kktc-2026"
    stored = await _stored(
        db_session,
        title_tr="Kuzey Kıbrıs Uçuşları %40 indirimli!",
        url=url,
        source_name=SCRAPE_SOURCE,
        discount_pct=40,
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
    )
    await db_session.commit()

    extended = ScrapedPromo(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs Uçuşları %40 indirimli!",
        summary_tr="",
        url=url,
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 30),
        discount_pct=40,
    )

    async def _fake_fetch(_client):
        return [extended]

    monkeypatch.setattr(promo_scrape, "fetch_pegasus", _fake_fetch)
    async with httpx.AsyncClient() as client:
        assert (await scrape_promotions(db_session, client=client))["updated"] == 1
        # The identical page again: seen, not changed.
        assert (await scrape_promotions(db_session, client=client))["updated"] == 1

    versions = (
        await db_session.execute(
            select(CampaignVersion).order_by(CampaignVersion.version_no)
        )
    ).scalars().all()
    assert [v.version_no for v in versions] == [1], "one edit, two sightings"
    assert versions[0].changed_fields["sale_ends"] == {
        "previous": "2026-08-23", "new": "2026-08-30"
    }
    assert versions[0].source_url == url
    await db_session.refresh(stored)
    assert stored.sale_ends == date(2026, 8, 30)
    assert stored.conflict_detected is None, "one source revising itself is not a conflict"
    assert len((await db_session.execute(select(CampaignSource))).scalars().all()) == 1


async def test_the_second_run_finds_the_merged_row_instead_of_re_inserting(
    db_session, monkeypatch
):
    """The merge survives repetition.

    The surviving row carries the airline's URL, so the article path can never
    find it by URL again -- it has to re-match by substance every run. If it
    did not, the duplicate would simply come back on the next tick.
    """
    await _stored(
        db_session,
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-40-indirimli-2026",
        source_name=SCRAPE_SOURCE,
        discount_pct=40,
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
    )
    twin = await find_duplicate(
        db_session,
        _candidate(
            title_tr="Pegasus'tan Kuzey Kıbrıs uçuşlarında %40 indirim",
            url="https://haber.example.com/pegasus-kktc-indirim",
            source_name="Haber",
            discount_pct=40,
        ),
    )
    assert twin is not None


# --- what must not merge ------------------------------------------------


async def test_two_partnership_campaigns_from_one_carrier_stay_apart(db_session):
    # Verbatim from the live table. Six words, five of them shared boilerplate:
    # title similarity alone reads 0.57 and would merge them, deleting one
    # partner's campaign outright. The partner's name is the whole difference.
    await _stored(
        db_session,
        title_tr="Pegasus BolBol & Polira İş Birliği",
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/pegasus-bolbol-polira",
        source_name=SCRAPE_SOURCE,
        sale_starts=date(2024, 10, 15),
        sale_ends=date(2026, 8, 31),
    )
    assert await find_duplicate(
        db_session,
        _candidate(
            title_tr="Pegasus BolBol ve Teknevia İş Birliği",
            url="https://www.flypgs.com/kampanyali-ucak-biletleri/pegasus-bolbol-teknevia",
            sale_starts=date(2024, 6, 25),
            sale_ends=date(2026, 12, 31),
        ),
    ) is None


async def test_the_same_headline_from_two_carriers_is_a_price_war_not_a_duplicate(db_session):
    await _stored(
        db_session,
        airline_code="PC",
        title_tr="Kuzey Kıbrıs uçuşlarında %40 indirim",
        url="https://example.com/pc-kktc",
    )
    assert await find_duplicate(
        db_session,
        _candidate(
            airline_code="TK",
            airline_name="Turkish Airlines",
            title_tr="Kuzey Kıbrıs uçuşlarında %40 indirim",
            url="https://example.com/tk-kktc",
        ),
    ) is None


def test_two_stated_rates_that_disagree_block_the_merge():
    row = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Yurt dışı uçuşlarda %50 indirim",
        summary_tr="",
        discount_pct=50,
        url="https://example.com/a",
        source_name="Haber",
        detected_at=NOW,
    )
    assert not is_duplicate(
        _candidate(
            title_tr="Yurt dışı uçuşlarda %25 indirim",
            url="https://example.com/b",
            discount_pct=25,
        ),
        row,
    )


def test_this_years_sale_does_not_swallow_last_years():
    """Identical title, disjoint windows: an annual re-run, not a duplicate."""
    row = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        summary_tr="",
        url="https://example.com/2025",
        source_name=SCRAPE_SOURCE,
        sale_starts=date(2025, 8, 21),
        sale_ends=date(2025, 8, 23),
        detected_at=NOW - timedelta(days=365),
    )
    assert not is_duplicate(
        _candidate(
            title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
            url="https://example.com/2026",
            sale_starts=date(2026, 8, 21),
            sale_ends=date(2026, 8, 23),
        ),
        row,
    )


def test_two_dateless_sightings_a_year_apart_are_not_one_campaign():
    # With no window on either side, how far apart we saw them is the only
    # timing signal there is.
    row = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs uçuşlarında %40 indirim",
        summary_tr="",
        url="https://example.com/old",
        source_name="Haber",
        detected_at=NOW - MAX_DETECTION_GAP - timedelta(days=1),
    )
    candidate = _candidate(
        title_tr="Kuzey Kıbrıs uçuşlarında %40 indirim", url="https://example.com/new"
    )
    assert not is_duplicate(candidate, row)
    # The same pair seen inside the window is the ordinary case, and does merge.
    row.detected_at = NOW - MAX_DETECTION_GAP + timedelta(days=1)
    assert is_duplicate(candidate, row)


# --- how the survivor is assembled --------------------------------------


def test_the_merged_row_keeps_the_richest_value_of_each_field():
    news = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Pegasus'tan Kuzey Kıbrıs uçuşlarında %40 indirim",
        summary_tr="Uzun ve ayrıntılı bir haber özeti; kampanyanın neden yapıldığını da anlatıyor.",
        discount_pct=None,
        markets="kuzey kıbrıs",
        url="https://haber.example.com/kktc",
        source_name="Haber",
        region="middle-east",
        detected_at=NOW - timedelta(days=2),
    )
    merge_candidate(
        news,
        _candidate(
            title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
            summary_tr="Kısa açıklama.",
            url="https://www.flypgs.com/kampanyali-ucak-biletleri/kktc-2026",
            discount_pct=40,
            sale_starts=date(2026, 8, 21),
            sale_ends=date(2026, 8, 23),
            detected_at=NOW,
        ),
    )

    # Null loses to a stated value, whichever side states it.
    assert news.discount_pct == 40
    assert (news.sale_starts, news.sale_ends) == (date(2026, 8, 21), date(2026, 8, 23))
    assert news.markets == "kuzey kıbrıs"
    assert news.region == "middle-east"
    # The airline's own naming and link for its own campaign...
    assert news.title_tr.startswith("Kuzey Kıbrıs Uçuşları")
    assert news.url.endswith("/kktc-2026")
    assert news.source_name == SCRAPE_SOURCE
    # ...and the reporting that actually explains it.
    assert news.summary_tr.startswith("Uzun ve ayrıntılı")
    assert news.detected_at == NOW - timedelta(days=2)


def test_a_refresh_never_nulls_out_a_window_it_simply_did_not_see():
    # What the article path does to a row it owns by URL. The curated seed and
    # this path share URLs, and a re-run used to overwrite the seed's verified
    # sale window with the extractor's blank -- turning a dated bar back into a
    # dateless point marker on every tick.
    row = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Pegasus: Kuzey Kıbrıs uçuşları salı-perşembe %40 indirimli",
        summary_tr="",
        discount_pct=40,
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kktc",
        source_name="Rakip Kampanya Takibi",
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
        detected_at=NOW,
    )
    merge_candidate(
        row,
        _candidate(
            title_tr="Pegasus: Kuzey Kıbrıs uçuşları salı-perşembe %40 indirimli",
            url="https://www.flypgs.com/kampanyali-ucak-biletleri/kktc",
            source_name="Rakip Kampanya Takibi",
            discount_pct=None,
        ),
        prefer_candidate=True,
    )
    assert (row.sale_starts, row.sale_ends) == (date(2026, 8, 21), date(2026, 8, 23))
    assert row.discount_pct == 40


# --- the backfill pass (python -m app.cli dedupe-promotions) ------------


async def test_the_backfill_collapses_rows_already_stored_twice(db_session):
    await _stored(
        db_session,
        title_tr="Pegasus: Kuzey Kıbrıs uçuşları salı-perşembe %40 indirimli",
        summary_tr="Haberin ayrıntılı özeti.",
        discount_pct=40,
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-40-indirimli",
        source_name="Rakip Kampanya Takibi",
        detected_at=NOW - timedelta(days=1),
    )
    await _stored(
        db_session,
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        discount_pct=40,
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-40-indirimli-2026",
        source_name=SCRAPE_SOURCE,
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
        detected_at=NOW,
    )
    # A genuinely different campaign from the same carrier, present throughout.
    await _stored(
        db_session,
        title_tr="Pegasus BolBol ve Teknevia İş Birliği",
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/pegasus-bolbol-teknevia",
        source_name=SCRAPE_SOURCE,
    )

    result = await dedupe_existing_promotions(db_session)
    assert result == {"scanned": 3, "merged": 1, "remaining": 2}

    rows = (await db_session.execute(select(Promotion).order_by(Promotion.title_tr))).scalars().all()
    kktc = next(r for r in rows if "Kıbrıs" in r.title_tr)
    assert len(rows) == 2
    assert kktc.url.endswith("-2026")
    assert (kktc.sale_starts, kktc.sale_ends) == (date(2026, 8, 21), date(2026, 8, 23))
    assert kktc.summary_tr == "Haberin ayrıntılı özeti."
    assert kktc.detected_at == NOW - timedelta(days=1)


async def test_the_backfill_is_a_no_op_on_a_clean_table(db_session):
    await _promo(db_session, slug="alpha")
    await _promo(db_session, slug="beta", airline="TK")
    assert (await dedupe_existing_promotions(db_session))["merged"] == 0


async def test_re_seeding_does_not_resurrect_a_campaign_that_was_merged_away(db_session):
    """The curated seed is the third writer, and it files by URL like the rest.

    Once its KKTC entry has been merged into Pegasus's own page for the same
    campaign, the merged row lives at the airline's URL -- so a re-seed finds
    nothing under the seed's URL and would cheerfully insert the duplicate back.
    """
    from app.ingest.promos_seed import PROMOS, _seed_promotion_rows

    seeded = next(p for p in PROMOS if "Kuzey Kıbrıs" in p.headline_tr)
    merged = await _stored(
        db_session,
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        discount_pct=40,
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-40-indirimli-2026",
        source_name=SCRAPE_SOURCE,
        sale_starts=date(2026, 8, 21),
        sale_ends=date(2026, 8, 23),
    )
    assert seeded.url != merged.url

    await _seed_promotion_rows(db_session, NOW)
    await db_session.flush()

    kktc = (
        await db_session.execute(
            select(Promotion).where(Promotion.title_tr.ilike("%kıbrıs%"))
        )
    ).scalars().all()
    assert len(kktc) == 1
    assert kktc[0].id == merged.id
    # The seed's window matches the airline's, and its markets are richer.
    assert (kktc[0].sale_starts, kktc[0].sale_ends) == (date(2026, 8, 21), date(2026, 8, 23))
    assert kktc[0].markets == seeded.markets
