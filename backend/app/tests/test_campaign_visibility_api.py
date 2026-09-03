"""Expired campaigns leaving the page, the three shortcut endpoints, and the
one order they all share.

The owner's clearest instruction about this surface was that a finished
campaign should not be on it. That is a *default*, not a deletion, so the tests
below come in pairs almost everywhere: hidden by default, returned when asked
for by name. The regression that matters most is the first one -- an expired
campaign reappearing in the default list is the failure this release exists to
prevent, and it would be invisible in every other assertion in this file.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response

from app.api.v1.promotions import (
    EXPORT_COLUMNS,
    count_promotions,
    export_promotions,
    list_active_promotions,
    list_expiring_promotions,
    list_promotions,
    list_upcoming_promotions,
    order_promotions,
)
from app.models.campaign_source import CampaignSource
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


async def _source(db, row: Promotion, *, tier: str) -> CampaignSource:
    source = CampaignSource(
        promotion_id=row.id,
        url=f"{row.url}#src-{tier}",
        source_name=tier,
        source_tier=tier,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db.add(source)
    await db.flush()
    return source


async def _list(db, **kwargs):
    return await list_promotions(response=Response(), db=db, **kwargs)


async def _titles(db, **kwargs) -> list[str]:
    return [row.title_tr for row in await _list(db, **kwargs)]


async def _expired(db, slug="bitti"):
    """A campaign whose sale window closed and which has no travel window --
    EXPIRED by services/campaign_status.py's decision table."""
    return await _promo(
        db,
        slug=slug,
        sale_starts=TODAY - timedelta(days=40),
        sale_ends=TODAY - timedelta(days=10),
    )


async def _active(db, slug="satista", *, ends_in=5, **kwargs):
    return await _promo(
        db,
        slug=slug,
        sale_starts=TODAY - timedelta(days=3),
        sale_ends=TODAY + timedelta(days=ends_in),
        **kwargs,
    )


async def _upcoming(db, slug="yakinda", *, starts_in=10):
    return await _promo(
        db,
        slug=slug,
        sale_starts=TODAY + timedelta(days=starts_in),
        sale_ends=TODAY + timedelta(days=starts_in + 10),
    )


async def _booking_closed(db, slug="satis-kapandi"):
    """Sale over, travel still running. Not expired, and specifically not
    "expiring" either -- there is nothing left to book."""
    return await _promo(
        db,
        slug=slug,
        sale_starts=TODAY - timedelta(days=30),
        sale_ends=TODAY - timedelta(days=2),
        travel_starts=TODAY + timedelta(days=5),
        travel_ends=TODAY + timedelta(days=60),
    )


# --- the default: expired campaigns are gone --------------------------------


async def test_an_expired_campaign_is_not_in_the_default_list(db_session):
    await _expired(db_session)
    await _active(db_session)
    assert await _titles(db_session) == ["satista"]


async def test_include_expired_brings_it_back_for_the_analyst(db_session):
    await _expired(db_session)
    await _active(db_session)
    assert set(await _titles(db_session, include_expired=True)) == {"bitti", "satista"}


async def test_the_count_agrees_with_the_list_about_expiry(db_session):
    await _expired(db_session)
    await _active(db_session)
    assert (await count_promotions(response=Response(), db=db_session))["total"] == 1
    payload = await count_promotions(
        response=Response(), db=db_session, include_expired=True
    )
    assert payload["total"] == 2


async def test_asking_for_expired_by_name_implies_include_expired(db_session):
    """A filter that silently contradicts itself is the worst kind of default:
    `?status=EXPIRED` must not come back empty."""
    await _expired(db_session)
    await _active(db_session)
    assert await _titles(db_session, status=["EXPIRED"]) == ["bitti"]


async def test_the_other_three_statuses_survive_the_new_default(db_session):
    await _active(db_session)
    await _upcoming(db_session)
    await _booking_closed(db_session)
    await _promo(db_session, slug="tarihsiz")
    assert set(await _titles(db_session)) == {
        "satista", "yakinda", "satis-kapandi", "tarihsiz",
    }


async def test_a_campaign_still_flyable_is_not_treated_as_expired(db_session):
    """BOOKING_CLOSED_TRAVEL_ACTIVE stays on the page: the competitor's
    capacity is still committed to those dates."""
    await _booking_closed(db_session)
    assert await _titles(db_session) == ["satis-kapandi"]


async def test_the_export_hides_expired_campaigns_too(db_session):
    await _expired(db_session)
    await _active(db_session)
    response = await export_promotions(format="json", db=db_session)
    import json

    rows = json.loads(bytes(response.body))
    assert [row["title_tr"] for row in rows] == ["satista"]


async def test_the_export_can_still_be_asked_for_everything(db_session):
    await _expired(db_session)
    await _active(db_session)
    response = await export_promotions(
        format="json", db=db_session, include_expired=True
    )
    import json

    assert len(json.loads(bytes(response.body))) == 2


# --- /active, /upcoming, /expiring ------------------------------------------


async def test_active_returns_only_what_can_be_bought_today(db_session):
    await _active(db_session)
    await _upcoming(db_session)
    await _booking_closed(db_session)
    await _expired(db_session)
    rows = await list_active_promotions(response=Response(), db=db_session)
    assert [row.title_tr for row in rows] == ["satista"]
    assert rows[0].status == "ACTIVE_BOOKING"


async def test_upcoming_returns_only_announced_but_unopened_campaigns(db_session):
    await _active(db_session)
    await _upcoming(db_session)
    rows = await list_upcoming_promotions(response=Response(), db=db_session)
    assert [row.title_tr for row in rows] == ["yakinda"]
    assert rows[0].status == "UPCOMING"


async def test_expiring_lists_campaigns_closing_inside_the_horizon(db_session):
    await _active(db_session, slug="yakin", ends_in=3)
    await _active(db_session, slug="uzak", ends_in=30)
    rows = await list_expiring_promotions(days=7, response=Response(), db=db_session)
    assert [row.title_tr for row in rows] == ["yakin"]


async def test_expiring_never_includes_a_campaign_whose_sale_already_closed(db_session):
    """The rule this endpoint exists to get right. A BOOKING_CLOSED campaign
    also has a `sale_ends` inside any backward-looking window, and calling it
    "bitmek üzere" would be the same error as showing an expired one, with a
    countdown on it."""
    await _booking_closed(db_session)
    await _expired(db_session)
    rows = await list_expiring_promotions(days=30, response=Response(), db=db_session)
    assert rows == []


async def test_expiring_excludes_an_open_ended_sale(db_session):
    # A deadline nobody set cannot be near.
    await _promo(db_session, slug="acik-uclu", sale_starts=TODAY - timedelta(days=2))
    rows = await list_expiring_promotions(days=30, response=Response(), db=db_session)
    assert rows == []


async def test_expiring_excludes_an_upcoming_campaign(db_session):
    await _upcoming(db_session, starts_in=2)
    rows = await list_expiring_promotions(days=30, response=Response(), db=db_session)
    assert rows == []


async def test_the_shortcut_endpoints_take_a_carrier_filter(db_session):
    await _active(db_session, slug="pc-satista", airline="PC")
    await _active(db_session, slug="tk-satista", airline="TK")
    rows = await list_active_promotions(
        airline=["TK"], response=Response(), db=db_session
    )
    assert [row.title_tr for row in rows] == ["tk-satista"]


# --- the shared order -------------------------------------------------------


async def test_buyable_campaigns_come_first_then_upcoming(db_session):
    await _upcoming(db_session)
    await _booking_closed(db_session)
    await _active(db_session)
    assert await _titles(db_session) == ["satista", "yakinda", "satis-kapandi"]


async def test_inside_the_active_bucket_the_soonest_deadline_wins(db_session):
    await _active(db_session, slug="uc-hafta", ends_in=21)
    await _active(db_session, slug="yarin", ends_in=1)
    await _active(db_session, slug="bir-hafta", ends_in=7)
    assert await _titles(db_session) == ["yarin", "bir-hafta", "uc-hafta"]


async def test_an_open_ended_sale_sorts_behind_every_stated_deadline(db_session):
    # "No deadline" is not "deadline is today".
    await _promo(db_session, slug="acik-uclu", sale_starts=TODAY - timedelta(days=1))
    await _active(db_session, slug="kapaniyor", ends_in=20)
    assert await _titles(db_session) == ["kapaniyor", "acik-uclu"]


async def test_undated_campaigns_sort_ahead_of_finished_ones(db_session):
    await _expired(db_session)
    await _promo(db_session, slug="tarihsiz")
    assert await _titles(db_session, include_expired=True) == ["tarihsiz", "bitti"]


async def test_newest_first_seen_is_the_tiebreaker_not_the_rule(db_session):
    await _active(
        db_session, slug="eski", ends_in=5, first_seen_at=NOW - timedelta(days=9)
    )
    await _active(
        db_session, slug="yeni", ends_in=5, first_seen_at=NOW - timedelta(hours=2)
    )
    assert await _titles(db_session) == ["yeni", "eski"]


async def test_the_export_uses_the_same_order_as_the_page(db_session):
    """A CSV that disagreed with the page it was downloaded from would be a bug
    report nobody could reproduce."""
    await _upcoming(db_session)
    await _active(db_session, slug="yarin", ends_in=1)
    await _active(db_session, slug="sonra", ends_in=15)

    import json

    response = await export_promotions(format="json", db=db_session)
    exported = [row["title_tr"] for row in json.loads(bytes(response.body))]
    assert exported == await _titles(db_session)
    assert exported == ["yarin", "sonra", "yakinda"]


def test_the_order_is_defined_once_and_is_stable():
    """`order_promotions` is a pure function of (rows, today), so two calls on
    the same input cannot disagree -- which is what lets the list and the
    export share it."""
    rows = [
        Promotion(
            id=uuid.UUID(int=index),
            airline_code="PC",
            airline_name="Pegasus",
            title_tr=f"row-{index}",
            summary_tr="",
            url=f"https://example.com/{index}",
            source_name="test",
            detected_at=NOW,
        )
        for index in range(5)
    ]
    first = [row.title_tr for row in order_promotions(rows, TODAY)]
    assert first == [row.title_tr for row in order_promotions(list(reversed(rows)), TODAY)]


# --- official_source_verified ------------------------------------------------


async def test_a_campaign_with_a_carrier_source_is_marked_verified(db_session):
    row = await _active(db_session)
    await _source(db_session, row, tier="official")
    assert (await _list(db_session))[0].official_source_verified is True


async def test_a_campaign_with_only_secondary_sources_is_not_verified(db_session):
    row = await _active(db_session)
    await _source(db_session, row, tier="secondary")
    await _source(db_session, row, tier="newsroom")
    served = (await _list(db_session))[0]
    assert served.official_source_verified is False
    assert served.source_count == 2


async def test_a_legacy_row_with_no_sources_is_not_verified(db_session):
    """False here is honest rather than pessimistic: nobody ever filed a
    source for it, so nobody ever verified it."""
    await _active(db_session)
    assert (await _list(db_session))[0].official_source_verified is False


async def test_the_export_carries_the_verification_flag(db_session):
    row = await _active(db_session)
    await _source(db_session, row, tier="official")
    response = await export_promotions(format="csv", db=db_session)
    chunks = [chunk async for chunk in response.body_iterator]
    text = "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)
    assert "official_source_verified" in EXPORT_COLUMNS
    assert text.strip().splitlines()[1].split(",")[
        EXPORT_COLUMNS.index("official_source_verified")
    ] == "true"


# --- campaign_kind on the read surface --------------------------------------


async def test_campaign_kind_rides_along_with_every_row(db_session):
    await _active(db_session, campaign_type="FLASH_SALE", campaign_kind="CAMPAIGN")
    assert (await _list(db_session))[0].campaign_kind == "CAMPAIGN"


async def test_the_list_can_be_filtered_to_one_kind(db_session):
    await _active(db_session, slug="fiyat", campaign_kind="CAMPAIGN")
    await _active(db_session, slug="mekanizma", campaign_kind="PROMOTION")
    assert await _titles(db_session, campaign_kind=["PROMOTION"]) == ["mekanizma"]


async def test_a_legacy_row_with_no_kind_is_still_served(db_session):
    await _active(db_session)
    assert (await _list(db_session))[0].campaign_kind is None


async def test_the_new_date_columns_are_served_when_stated(db_session):
    await _active(
        db_session,
        ticketing_end=TODAY + timedelta(days=20),
        campaign_start=TODAY - timedelta(days=3),
    )
    served = (await _list(db_session))[0]
    assert served.ticketing_end == TODAY + timedelta(days=20)
    assert served.campaign_start == TODAY - timedelta(days=3)
    # Nothing was copied into the edges the row never stated.
    assert served.ticketing_start is None
    assert served.campaign_end is None
