"""PR7's read surface: the analyst filters, the count/pagination contract, the
per-campaign history endpoints and the CSV/JSON export.

What is actually at risk here, and what each block below pins down:

**The count must be a promise about the list, not a second opinion.** Three
endpoints share one `_matching_promotions()` for exactly that reason, and the
pagination tests assert the agreement rather than the implementation.

**Status is computed, so it cannot be filtered in SQL.** The status filter runs
in Python after the query, which means it interacts with `limit`/`offset`:
slicing before the status pass would hand back short pages. The pagination
tests use a status filter for that reason.

**A legacy row must survive every new filter.** ~200 rows in production have
NULL campaign_type, business_class, confidence_band and review_required. An
unfiltered request has to keep returning them, and `review_required=false` has
to include them -- "never queued for review" is not "flagged".
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from app.api.v1.promotions import (
    EXPORT_COLUMNS,
    EXPORT_ROW_CAP,
    count_promotions,
    export_promotions,
    list_promotion_sources,
    list_promotion_versions,
    list_promotions,
)
from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


async def _promo(db, *, slug: str, airline: str = "PC", **kwargs) -> Promotion:
    row = Promotion(
        airline_code=airline,
        airline_name=f"{airline} Havayolları",
        title_tr=kwargs.pop("title_tr", slug),
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
    return await list_promotions(response=Response(), db=db, **kwargs)


async def _count(db, **kwargs) -> int:
    payload = await count_promotions(response=Response(), db=db, **kwargs)
    return payload["total"]


async def _csv_text(response) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)


# --- the serializer -------------------------------------------------------


async def test_every_row_carries_its_computed_status(db_session):
    await _promo(
        db_session,
        slug="running",
        sale_starts=TODAY - timedelta(days=3),
        sale_ends=TODAY + timedelta(days=3),
    )
    await _promo(
        db_session,
        slug="ahead",
        sale_starts=TODAY + timedelta(days=10),
        sale_ends=TODAY + timedelta(days=20),
    )
    await _promo(db_session, slug="dateless")

    by_title = {row.title_tr: row for row in await _list(db_session)}
    assert by_title["running"].status == "ACTIVE_BOOKING"
    assert by_title["ahead"].status == "UPCOMING"
    # Nothing stated at all is UNKNOWN, never a default of "active".
    assert by_title["dateless"].status == "UNKNOWN"


async def test_the_intelligence_columns_ride_along_with_every_row(db_session):
    await _promo(
        db_session,
        slug="typed",
        campaign_type="FLASH_SALE",
        business_class="ACTIVE_CAMPAIGN",
        route_scope="OND",
        ond="IST-LHR",
        origin_code="IST",
        dest_code="LHR",
        route_json={"origin": {"country": "Türkiye"}, "dest": {"country": "Birleşik Krallık"}},
        confidence_score=0.91,
        confidence_band="high",
        review_required=False,
        conflict_detected=True,
        classification_reason="Sayfada satış dönemi ve indirim oranı açıkça yazıyor.",
        attrs_json={"promo_code": "FLY30", "currency": "TRY", "price_floor": 1299},
        evidence_json={"sale_ends": {"value": "2026-09-30", "source_text": "30 Eylül'e kadar"}},
        date_flags_json={"inferred_year": True},
        first_seen_at=NOW - timedelta(days=4),
        last_changed_at=NOW - timedelta(days=1),
    )

    row = (await _list(db_session))[0]
    assert row.campaign_type == "FLASH_SALE"
    assert row.business_class == "ACTIVE_CAMPAIGN"
    assert (row.route_scope, row.ond, row.origin_code, row.dest_code) == (
        "OND", "IST-LHR", "IST", "LHR",
    )
    assert row.confidence_score == pytest.approx(0.91)
    assert row.confidence_band == "high"
    assert row.conflict_detected is True
    assert row.review_required is False
    assert row.classification_reason.startswith("Sayfada")
    assert row.attrs_json["promo_code"] == "FLY30"
    assert row.evidence_json["sale_ends"]["source_text"] == "30 Eylül'e kadar"
    assert row.date_flags_json == {"inferred_year": True}
    assert row.first_seen_at is not None and row.last_changed_at is not None


async def test_a_legacy_row_serializes_with_nulls_rather_than_invented_values(db_session):
    await _promo(db_session, slug="legacy")
    row = (await _list(db_session))[0]
    assert (row.campaign_type, row.business_class, row.route_scope, row.ond) == (
        None, None, None, None,
    )
    assert (row.version_count, row.source_count) == (0, 0)
    # Still fully renderable: the fields the page has always needed are there.
    assert row.sale_range_tr == "Belirtilmedi"


async def test_version_and_source_counts_come_from_the_child_tables(db_session):
    parent = await _promo(db_session, slug="tracked")
    other = await _promo(db_session, slug="untracked", airline="TK")
    db_session.add_all(
        [
            CampaignVersion(promotion_id=parent.id, version_no=1, changed_fields={"a": {}}),
            CampaignVersion(promotion_id=parent.id, version_no=2, changed_fields={"b": {}}),
            CampaignSource(promotion_id=parent.id, url="https://a.example.com"),
            CampaignSource(promotion_id=parent.id, url="https://b.example.com"),
            CampaignSource(promotion_id=parent.id, url="https://c.example.com"),
        ]
    )
    await db_session.flush()

    by_title = {row.title_tr: row for row in await _list(db_session)}
    assert (by_title["tracked"].version_count, by_title["tracked"].source_count) == (2, 3)
    assert (by_title["untracked"].version_count, by_title["untracked"].source_count) == (0, 0)
    assert other.id is not None


# --- the new filters ------------------------------------------------------


async def test_campaign_type_is_multi_select(db_session):
    await _promo(db_session, slug="flash", campaign_type="FLASH_SALE")
    await _promo(db_session, slug="early", campaign_type="EARLY_BOOKING")
    await _promo(db_session, slug="black", campaign_type="BLACK_FRIDAY")
    await _promo(db_session, slug="untyped")

    rows = await _list(db_session, campaign_type=["FLASH_SALE", "BLACK_FRIDAY"])
    assert {r.title_tr for r in rows} == {"flash", "black"}
    # Absent means every type, including the untyped legacy row.
    assert len(await _list(db_session)) == 4


async def test_business_class_separates_a_campaign_from_a_standing_offer(db_session):
    await _promo(db_session, slug="real", business_class="ACTIVE_CAMPAIGN")
    await _promo(db_session, slug="student", business_class="EVERGREEN_OFFER")

    rows = await _list(db_session, business_class=["ACTIVE_CAMPAIGN"])
    assert [r.title_tr for r in rows] == ["real"]


async def test_status_filters_on_the_computed_value(db_session):
    await _promo(
        db_session,
        slug="live",
        sale_starts=TODAY - timedelta(days=1),
        sale_ends=TODAY + timedelta(days=1),
    )
    await _promo(
        db_session,
        slug="done",
        sale_starts=TODAY - timedelta(days=30),
        sale_ends=TODAY - timedelta(days=10),
    )
    await _promo(
        db_session,
        slug="flying",
        sale_starts=TODAY - timedelta(days=30),
        sale_ends=TODAY - timedelta(days=10),
        travel_starts=TODAY,
        travel_ends=TODAY + timedelta(days=30),
    )

    assert [r.title_tr for r in await _list(db_session, status=["ACTIVE_BOOKING"])] == ["live"]
    assert [r.title_tr for r in await _list(db_session, status=["EXPIRED"])] == ["done"]
    assert [
        r.title_tr for r in await _list(db_session, status=["BOOKING_CLOSED_TRAVEL_ACTIVE"])
    ] == ["flying"]
    # Multi-select widens rather than intersects.
    assert len(await _list(db_session, status=["EXPIRED", "ACTIVE_BOOKING"])) == 2


async def test_country_matches_either_the_market_list_or_the_resolved_route(db_session):
    await _promo(db_session, slug="market", markets_json={"countries": ["Almanya"]})
    await _promo(
        db_session,
        slug="route",
        route_json={"origin": {"country": "Türkiye"}, "dest": {"country": "Almanya"}},
    )
    await _promo(db_session, slug="elsewhere", markets_json={"countries": ["Japonya"]})

    # Case and surrounding whitespace are the user's, not the data's.
    rows = await _list(db_session, country="  almanya ")
    assert {r.title_tr for r in rows} == {"market", "route"}


async def test_region_matches_the_flat_column_and_both_json_shapes(db_session):
    await _promo(db_session, slug="flat", region="europe")
    await _promo(db_session, slug="markets", markets_json={"regions": ["europe"]})
    await _promo(db_session, slug="routed", route_json={"dest": {"region": "europe"}})
    await _promo(db_session, slug="other", region="asia")

    rows = await _list(db_session, region=["europe"])
    assert {r.title_tr for r in rows} == {"flat", "markets", "routed"}
    assert len(await _list(db_session, region=["europe", "asia"])) == 4


async def test_min_discount_excludes_a_campaign_with_no_stated_rate(db_session):
    await _promo(db_session, slug="deep", discount_pct=50)
    await _promo(db_session, slug="shallow", discount_pct=15)
    await _promo(db_session, slug="unstated", discount_pct=None)

    rows = await _list(db_session, min_discount=30)
    # "At least 30%" is a claim; an unknown rate cannot support it.
    assert [r.title_tr for r in rows] == ["deep"]


async def test_band_filter_narrows_to_the_named_bands(db_session):
    await _promo(db_session, slug="high", confidence_band="high")
    await _promo(db_session, slug="medium", confidence_band="medium")
    await _promo(db_session, slug="never-assessed", confidence_band=None)

    assert [r.title_tr for r in await _list(db_session, band=["high"])] == ["high"]
    assert len(await _list(db_session, band=["high", "medium"])) == 2
    # Unfiltered still serves the never-assessed legacy row.
    assert len(await _list(db_session)) == 3


async def test_review_required_false_includes_the_never_queued_legacy_row(db_session):
    await _promo(db_session, slug="queued", review_required=True)
    await _promo(db_session, slug="clean", review_required=False)
    await _promo(db_session, slug="legacy", review_required=None)

    assert [r.title_tr for r in await _list(db_session, review_required=True)] == ["queued"]
    assert {r.title_tr for r in await _list(db_session, review_required=False)} == {
        "clean",
        "legacy",
    }


async def test_filters_combine_as_an_intersection(db_session):
    await _promo(
        db_session,
        slug="match",
        airline="TK",
        campaign_type="FLASH_SALE",
        discount_pct=40,
        region="europe",
    )
    await _promo(
        db_session,
        slug="wrong-carrier",
        airline="PC",
        campaign_type="FLASH_SALE",
        discount_pct=40,
        region="europe",
    )
    await _promo(
        db_session, slug="wrong-type", airline="TK", campaign_type="EARLY_BOOKING", discount_pct=40
    )

    rows = await _list(
        db_session,
        airline=["TK"],
        campaign_type=["FLASH_SALE"],
        min_discount=30,
        region=["europe"],
    )
    assert [r.title_tr for r in rows] == ["match"]


# --- pagination and the count endpoint ------------------------------------


async def test_pages_partition_the_filtered_set_and_the_count_agrees(db_session):
    for index in range(7):
        await _promo(
            db_session,
            slug=f"row-{index}",
            detected_at=NOW - timedelta(minutes=index),
        )

    total = await _count(db_session)
    assert total == 7

    first = await _list(db_session, limit=3)
    second = await _list(db_session, limit=3, offset=3)
    third = await _list(db_session, limit=3, offset=6)
    assert [len(first), len(second), len(third)] == [3, 3, 1]
    # Newest sighting first, and no row appears on two pages.
    ids = [r.id for r in first + second + third]
    assert len(set(ids)) == total
    assert [r.title_tr for r in first] == ["row-0", "row-1", "row-2"]


async def test_the_count_applies_the_python_side_filters_too(db_session):
    """The trap this guards: `status` cannot be filtered in SQL, so a count
    written as a `SELECT count(*)` would have ignored it and told the UI it had
    more pages than rows."""
    await _promo(
        db_session,
        slug="live",
        sale_starts=TODAY - timedelta(days=1),
        sale_ends=TODAY + timedelta(days=1),
    )
    await _promo(
        db_session,
        slug="over",
        sale_starts=TODAY - timedelta(days=9),
        sale_ends=TODAY - timedelta(days=2),
    )

    assert await _count(db_session, status=["ACTIVE_BOOKING"]) == 1
    assert len(await _list(db_session, status=["ACTIVE_BOOKING"])) == 1


async def test_no_limit_still_means_the_whole_window(db_session):
    """The calendar overlay and the timeline both call this endpoint with no
    limit at all -- pagination had to be opt-in or both would have silently
    started truncating."""
    for index in range(4):
        await _promo(db_session, slug=f"p{index}")
    assert len(await _list(db_session)) == 4


# --- versions and sources -------------------------------------------------


async def test_versions_come_back_newest_edit_first(db_session):
    promo = await _promo(db_session, slug="edited")
    db_session.add_all(
        [
            CampaignVersion(
                promotion_id=promo.id,
                version_no=1,
                changed_fields={"sale_ends": {"previous": None, "new": "2026-08-23"}},
                source_url="https://example.com/edited",
            ),
            CampaignVersion(
                promotion_id=promo.id,
                version_no=2,
                changed_fields={"discount_pct": {"previous": 30, "new": 40}},
                source_url="https://example.com/edited",
            ),
        ]
    )
    await db_session.flush()

    rows = await list_promotion_versions(promo.id, response=Response(), db=db_session)
    assert [r.version_no for r in rows] == [2, 1]
    assert rows[0].changed_fields["discount_pct"] == {"previous": 30, "new": 40}
    assert rows[1].source_url == "https://example.com/edited"


async def test_versions_of_an_unknown_campaign_are_a_404_not_an_empty_list(db_session):
    with pytest.raises(HTTPException) as caught:
        await list_promotion_versions(uuid.uuid4(), response=Response(), db=db_session)
    assert caught.value.status_code == 404


async def test_sources_are_ordered_most_official_first(db_session):
    promo = await _promo(db_session, slug="corroborated")
    db_session.add_all(
        [
            CampaignSource(
                promotion_id=promo.id,
                url="https://haber.example.com/x",
                source_name="Haber",
                source_tier="secondary",
                source_quality=0.4,
                first_seen_at=NOW - timedelta(days=3),
            ),
            CampaignSource(
                promotion_id=promo.id,
                url="https://airline.example.com/kampanya",
                source_name="Resmî sayfa",
                source_tier="official",
                source_quality=1.0,
                first_seen_at=NOW,
            ),
            CampaignSource(
                promotion_id=promo.id,
                url="https://press.example.com/y",
                source_tier="newsroom",
                source_quality=0.8,
            ),
        ]
    )
    await db_session.flush()

    rows = await list_promotion_sources(promo.id, response=Response(), db=db_session)
    assert [r.source_tier for r in rows] == ["official", "newsroom", "secondary"]
    assert rows[0].source_quality == pytest.approx(1.0)


async def test_a_campaign_with_no_recorded_source_returns_an_empty_list(db_session):
    promo = await _promo(db_session, slug="bare")
    assert await list_promotion_sources(promo.id, response=Response(), db=db_session) == []


# --- export ---------------------------------------------------------------


async def test_csv_export_has_the_documented_header_and_one_row_per_campaign(db_session):
    await _promo(
        db_session,
        slug="exported",
        airline="TK",
        title_tr="Avrupa'ya %40 indirim",
        campaign_type="PERCENT_DISCOUNT",
        business_class="ACTIVE_CAMPAIGN",
        sale_starts=TODAY - timedelta(days=1),
        sale_ends=TODAY + timedelta(days=6),
        travel_starts=TODAY + timedelta(days=10),
        travel_ends=TODAY + timedelta(days=100),
        origin_code="IST",
        dest_code="CDG",
        ond="IST-CDG",
        route_scope="OND",
        discount_pct=40,
        attrs_json={"currency": "EUR", "price_floor": 99, "promo_code": "EUR40"},
        confidence_score=0.875,
        confidence_band="high",
        first_seen_at=NOW - timedelta(days=2),
        last_changed_at=NOW - timedelta(days=1),
    )

    response = await export_promotions(db=db_session)
    text = await _csv_text(response)
    rows = list(csv.reader(io.StringIO(text)))

    assert tuple(rows[0]) == EXPORT_COLUMNS
    assert len(rows) == 2
    record = dict(zip(EXPORT_COLUMNS, rows[1], strict=True))
    assert record["carrier"] == "TK"
    assert record["campaign_name"] == "Avrupa'ya %40 indirim"
    assert record["campaign_type"] == "PERCENT_DISCOUNT"
    assert record["status"] == "ACTIVE_BOOKING"
    assert record["booking_end"] == (TODAY + timedelta(days=6)).isoformat()
    assert record["travel_start"] == (TODAY + timedelta(days=10)).isoformat()
    assert (record["origin"], record["destination"], record["ond"]) == ("IST", "CDG", "IST-CDG")
    assert record["discount_pct"] == "40"
    assert (record["currency"], record["price_floor"]) == ("EUR", "99")
    assert record["promo_code"] == "EUR40"
    assert record["confidence_score"] == "0.875"
    assert record["source_url"] == "https://example.com/exported"
    assert response.headers["X-Row-Cap-Reached"] == "false"
    assert "aerointel-kampanyalar-" in response.headers["content-disposition"]


async def test_an_unclassified_row_exports_as_empty_cells_not_as_the_word_none(db_session):
    await _promo(db_session, slug="legacy")
    rows = list(csv.reader(io.StringIO(await _csv_text(await export_promotions(db=db_session)))))
    record = dict(zip(EXPORT_COLUMNS, rows[1], strict=True))
    assert record["campaign_type"] == ""
    assert record["discount_pct"] == ""
    assert record["price_floor"] == ""
    assert record["status"] == "UNKNOWN"


async def test_the_export_honours_the_same_filters_as_the_list(db_session):
    await _promo(db_session, slug="tk", airline="TK", campaign_type="FLASH_SALE")
    await _promo(db_session, slug="pc", airline="PC", campaign_type="FLASH_SALE")

    text = await _csv_text(await export_promotions(airline=["TK"], db=db_session))
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[1][0] == "TK"


async def test_the_export_is_capped_and_says_so(db_session, monkeypatch):
    """The real cap is 2000 rows; inserting 2001 of them to prove it would make
    this suite a load test. The cap value is patched, the behaviour is not."""
    import app.api.v1.promotions as module

    monkeypatch.setattr(module, "EXPORT_ROW_CAP", 2)
    for index in range(4):
        await _promo(db_session, slug=f"row-{index}", detected_at=NOW - timedelta(minutes=index))

    response = await export_promotions(db=db_session)
    rows = list(csv.reader(io.StringIO(await _csv_text(response))))
    assert len(rows) == 3, "header + the capped two"
    assert response.headers["X-Row-Cap-Reached"] == "true"
    # Truncation takes the newest, because the order is newest-sighting-first.
    assert [r[1] for r in rows[1:]] == ["row-0", "row-1"]


async def test_json_export_returns_the_same_rows_the_api_serves(db_session):
    import json

    await _promo(db_session, slug="json-row", campaign_type="FLASH_SALE", discount_pct=25)
    response = await export_promotions(format="json", db=db_session)
    payload = json.loads(response.body)

    assert len(payload) == 1
    assert payload[0]["campaign_type"] == "FLASH_SALE"
    assert payload[0]["discount_pct"] == 25
    # The computed fields the page relies on are part of the export too.
    assert payload[0]["status"] == "UNKNOWN"
    assert payload[0]["sale_range_tr"] == "Belirtilmedi"
    assert "aerointel-kampanyalar-" in response.headers["content-disposition"]


def test_the_export_cap_is_the_documented_one():
    # A future edit that raises this has to face the 30s Vercel limit first.
    assert EXPORT_ROW_CAP == 2000
