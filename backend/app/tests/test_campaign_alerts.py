"""The alert generator, which has exactly one job: fire once.

Every test below is really a test of that. The generator is called from two
workflows on purpose, GitHub's cron is measured 2-2.75 hours late on this repo,
and a manual dispatch can add a third run in the same hour -- so "it produced
an alert" is the easy half and "it produced it once, and would still have
produced it if the run had been skipped" is the half that decides whether the
feature is usable. The dedupe-key and delayed-cron tests are therefore the
load-bearing ones here; the per-type tests exist to keep them honest.

The other thing worth guarding is the first run. A rule written as a query over
state, rather than over "what changed since I last looked", will happily
announce every campaign that ever expired the first time it is executed against
a real table -- 200 legacy rows, all at once, on the morning the feature ships.
`test_ancient_expired_campaign_does_not_alert` is that guard.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import Response
from sqlalchemy import select

from app.api.v1.campaign_alerts import list_campaign_alerts
from app.email.render import render_newsletter_html
from app.models.campaign_alert import CampaignAlert
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.services.campaign_alerts import (
    _boosts,
    _priority,
    generate_alerts,
    recent_alert_highlights,
)

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


async def _promo(db, **overrides) -> Promotion:
    """A publishable campaign row. Defaults are deliberately alert-free: no
    rival carrier, no discount, no dates -- so each test opts in to exactly the
    one property it is about."""
    fields = {
        "airline_code": "XX",
        "airline_name": "Test Havayolu",
        "title_tr": "Test kampanyası",
        "summary_tr": "",
        "url": f"https://example.com/kampanya/{uuid.uuid4()}",
        "source_name": "Test",
        "detected_at": NOW,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
    }
    fields.update(overrides)
    promotion = Promotion(**fields)
    db.add(promotion)
    await db.commit()
    return promotion


async def _alerts(db) -> list[CampaignAlert]:
    return list(
        (await db.execute(select(CampaignAlert).order_by(CampaignAlert.dedupe_key)))
        .scalars()
        .all()
    )


# --- the priority matrix (no DB: it is a pure function of one row) ----------


def _row(**overrides) -> Promotion:
    fields = {
        "airline_code": "XX",
        "airline_name": "Test Havayolu",
        "title_tr": "Test",
        "url": "https://example.com/x",
        "source_name": "Test",
    }
    fields.update(overrides)
    return Promotion(**fields)


def test_an_ordinary_campaign_is_medium():
    assert _priority(_row(), "NEW") == ("MEDIUM", [])


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"airline_code": "QR"}, "rival_carrier"),
        ({"discount_pct": 40}, "deep_discount"),
        ({"campaign_type": "FLASH_SALE"}, "flash_sale"),
        (
            {"sale_starts": date(2026, 9, 1), "sale_ends": date(2026, 9, 8)},
            "short_booking_window",
        ),
    ],
)
def test_each_boost_lifts_a_single_alert_to_high(overrides, reason):
    priority, reasons = _priority(_row(**overrides), "NEW")
    assert priority == "HIGH"
    assert reasons == [reason]


def test_a_discount_below_the_threshold_is_not_a_boost():
    # 39% is a promotion; 40% is a price move. The line has to be exactly there
    # or the matrix is decorative.
    assert _boosts(_row(discount_pct=39)) == []
    assert _boosts(_row(discount_pct=40)) == ["deep_discount"]


def test_a_booking_window_of_exactly_a_week_still_boosts():
    week = {"sale_starts": date(2026, 9, 1), "sale_ends": date(2026, 9, 8)}
    eight_days = {"sale_starts": date(2026, 9, 1), "sale_ends": date(2026, 9, 9)}
    assert _boosts(_row(**week)) == ["short_booking_window"]
    assert _boosts(_row(**eight_days)) == []


def test_two_boosts_stack_into_critical():
    priority, reasons = _priority(_row(airline_code="QR", discount_pct=50), "NEW")
    assert priority == "CRITICAL"
    assert set(reasons) == {"rival_carrier", "deep_discount"}


def test_four_boosts_are_still_critical_not_something_louder():
    priority, reasons = _priority(
        _row(
            airline_code="QR",
            discount_pct=60,
            campaign_type="FLASH_SALE",
            sale_starts=date(2026, 9, 1),
            sale_ends=date(2026, 9, 3),
        ),
        "NEW",
    )
    assert priority == "CRITICAL"
    assert len(reasons) == 4


def test_low_confidence_sits_one_rung_lower_across_the_whole_ladder():
    # An extraction we do not trust must never reach CRITICAL, however
    # rival-shaped it looks -- see the matrix in the module docstring.
    assert _priority(_row(), "LOW_CONFIDENCE")[0] == "INFO"
    assert _priority(_row(airline_code="QR"), "LOW_CONFIDENCE")[0] == "MEDIUM"
    assert _priority(_row(airline_code="QR", discount_pct=45), "LOW_CONFIDENCE")[0] == "HIGH"


# --- one alert per type ----------------------------------------------------


async def test_a_freshly_seen_campaign_produces_a_new_alert(db_session):
    await _promo(db_session, airline_name="Qatar Airways", title_tr="Avrupa'ya %30 indirim")

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["NEW"] == 1
    alert = (await _alerts(db_session))[0]
    assert alert.alert_type == "NEW"
    assert alert.title_tr == "Yeni kampanya — Qatar Airways: Avrupa'ya %30 indirim"


async def test_a_campaign_first_seen_last_week_is_not_new(db_session):
    await _promo(db_session, first_seen_at=NOW - timedelta(days=7))
    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["NEW"] == 0


async def test_a_version_row_produces_a_change_alert_that_says_what_moved(db_session):
    promotion = await _promo(
        db_session, airline_name="Qatar Airways", first_seen_at=NOW - timedelta(days=30)
    )
    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={
                "travel_ends": {"previous": "2026-10-31", "new": "2026-11-15"},
            },
        )
    )
    await db_session.commit()

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["CHANGE"] == 1
    alert = (await _alerts(db_session))[0]
    # The ISO strings the version table stores must never reach a reader.
    assert alert.title_tr == (
        "Qatar Airways kampanyasında seyahat bitişi değişti: 31 Ekim 2026 → 15 Kasım 2026"
    )
    assert alert.detail_json["version_no"] == 1


async def test_a_change_touching_several_fields_leads_with_the_one_that_matters(db_session):
    promotion = await _promo(db_session, first_seen_at=NOW - timedelta(days=30))
    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={
                "title_tr": {"previous": "Eski", "new": "Yeni"},
                "sale_ends": {"previous": "2026-12-31", "new": "2026-12-10"},
                "discount_pct": {"previous": 30, "new": 45},
            },
        )
    )
    await db_session.commit()

    await generate_alerts(db_session, today=TODAY, now=NOW)

    alert = (await _alerts(db_session))[0]
    assert "satış bitişi değişti" in alert.title_tr
    assert "(+2 alan daha)" in alert.title_tr


async def test_a_change_nobody_can_read_writes_no_alert(db_session):
    # A re-scored confidence blob is a real version row and a non-event.
    promotion = await _promo(db_session, first_seen_at=NOW - timedelta(days=30))
    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={"evidence_json": {"previous": None, "new": {"a": 1}}},
        )
    )
    await db_session.commit()

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["CHANGE"] == 0


async def test_a_sale_window_closing_in_two_days_produces_an_expiring_alert(db_session):
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY - timedelta(days=10),
        sale_ends=TODAY + timedelta(days=2),
    )

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["EXPIRING"] == 1
    alert = (await _alerts(db_session))[0]
    assert "2 gün sonra bitiyor" in alert.title_tr
    assert alert.detail_json["days_left"] == 2


async def test_a_sale_window_closing_today_says_so_in_turkish(db_session):
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY - timedelta(days=10),
        sale_ends=TODAY,
    )
    await generate_alerts(db_session, today=TODAY, now=NOW)
    assert "bugün bitiyor" in (await _alerts(db_session))[0].title_tr


async def test_a_campaign_that_has_not_opened_yet_is_not_expiring(db_session):
    # Sale runs entirely inside the three-day horizon but starts tomorrow: it
    # is UPCOMING, and "bitmek üzere" would be a lie.
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY + timedelta(days=1),
        sale_ends=TODAY + timedelta(days=2),
    )
    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["EXPIRING"] == 0


async def test_a_sale_window_that_closed_yesterday_produces_an_expired_alert(db_session):
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY - timedelta(days=20),
        sale_ends=TODAY - timedelta(days=1),
    )

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["EXPIRED"] == 1
    assert "sona erdi" in (await _alerts(db_session))[0].title_tr


async def test_a_review_flagged_row_alerts_even_though_it_is_unpublishable(db_session):
    # The whole point: it is flagged *because* it scored badly, and a bad score
    # is often a low band -- the band filter the public endpoints use would
    # hide exactly the rows the review queue exists for.
    await _promo(db_session, review_required=True, confidence_band="low")

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["LOW_CONFIDENCE"] == 1
    alert = (await _alerts(db_session))[0]
    assert alert.priority == "INFO"
    assert alert.title_tr.startswith("İnceleme gerekiyor —")


async def test_a_superseded_campaign_alerts_about_nothing(db_session):
    await _promo(
        db_session,
        superseded_at=NOW,
        review_required=True,
        sale_starts=TODAY - timedelta(days=5),
        sale_ends=TODAY + timedelta(days=1),
    )
    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["total"] == 0


# --- idempotency and the cron ----------------------------------------------


async def test_running_twice_writes_the_same_alerts_once(db_session):
    await _promo(
        db_session,
        airline_code="QR",
        sale_starts=TODAY - timedelta(days=1),
        sale_ends=TODAY + timedelta(days=1),
        review_required=True,
    )

    first = await generate_alerts(db_session, today=TODAY, now=NOW)
    second = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert first["total"] == 3  # NEW + EXPIRING + LOW_CONFIDENCE
    assert second["total"] == 0
    assert second["duplicates"] == 3
    assert len(await _alerts(db_session)) == 3


async def test_the_same_edit_seen_twice_is_still_one_change_alert(db_session):
    promotion = await _promo(db_session, first_seen_at=NOW - timedelta(days=30))
    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={"discount_pct": {"previous": 20, "new": 45}},
        )
    )
    await db_session.commit()

    await generate_alerts(db_session, today=TODAY, now=NOW)
    await generate_alerts(db_session, today=TODAY, now=NOW)

    assert len([a for a in await _alerts(db_session) if a.alert_type == "CHANGE"]) == 1


async def test_a_second_edit_is_a_second_alert(db_session):
    promotion = await _promo(db_session, first_seen_at=NOW - timedelta(days=30))
    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={"discount_pct": {"previous": 20, "new": 30}},
        )
    )
    await db_session.commit()
    await generate_alerts(db_session, today=TODAY, now=NOW)

    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=2,
            changed_fields={"discount_pct": {"previous": 30, "new": 45}},
        )
    )
    await db_session.commit()
    second = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert second["CHANGE"] == 1
    assert len([a for a in await _alerts(db_session) if a.alert_type == "CHANGE"]) == 2


async def test_a_delayed_cron_still_catches_an_expiring_campaign(db_session):
    """The run that should have happened on day X never did. The one on X+1
    must still warn about a sale window closing on X+2 -- and must warn once."""
    sale_ends = TODAY + timedelta(days=2)
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY - timedelta(days=5),
        sale_ends=sale_ends,
    )

    # Day X's run is skipped entirely; the first run that happens is X+1's.
    late = await generate_alerts(
        db_session, today=TODAY + timedelta(days=1), now=NOW + timedelta(days=1)
    )
    assert late["EXPIRING"] == 1

    # ...and the day after that, the bucket is the same sale_ends date, so the
    # reader is not told a second time.
    later = await generate_alerts(
        db_session, today=TODAY + timedelta(days=2), now=NOW + timedelta(days=2)
    )
    assert later["EXPIRING"] == 0
    assert len([a for a in await _alerts(db_session) if a.alert_type == "EXPIRING"]) == 1


async def test_a_delayed_cron_still_catches_an_expiry_it_slept_through(db_session):
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=30),
        sale_starts=TODAY - timedelta(days=20),
        sale_ends=TODAY - timedelta(days=2),  # two days ago, not yesterday
    )
    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["EXPIRED"] == 1


async def test_ancient_expired_campaign_does_not_alert(db_session):
    """The first-run flood guard. Two hundred legacy rows whose windows closed
    in 2024 must not become two hundred alerts on the morning this ships."""
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=400),
        detected_at=NOW - timedelta(days=400),
        sale_starts=TODAY - timedelta(days=400),
        sale_ends=TODAY - timedelta(days=380),
    )
    await _promo(
        db_session,
        first_seen_at=NOW - timedelta(days=400),
        detected_at=NOW - timedelta(days=400),
        review_required=True,
    )

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)

    assert summary["total"] == 0
    assert await _alerts(db_session) == []


async def test_an_ancient_version_row_does_not_alert(db_session):
    promotion = await _promo(db_session, first_seen_at=NOW - timedelta(days=400))
    version = CampaignVersion(
        promotion_id=promotion.id,
        version_no=1,
        changed_fields={"discount_pct": {"previous": 10, "new": 20}},
    )
    db_session.add(version)
    await db_session.commit()
    # server_default now() cannot be back-dated at insert time, so age it after.
    version.created_at = NOW - timedelta(days=400)
    await db_session.commit()

    summary = await generate_alerts(db_session, today=TODAY, now=NOW)
    assert summary["CHANGE"] == 0


# --- the read endpoint -----------------------------------------------------


async def _seed_alert(db, promotion, *, priority: str, created_at, acknowledged=False, key=None):
    alert = CampaignAlert(
        promotion_id=promotion.id,
        alert_type="NEW",
        priority=priority,
        title_tr=f"{priority} uyarısı",
        detail_json={"airline_name": promotion.airline_name},
        dedupe_key=key or f"{promotion.id}:NEW:{uuid.uuid4()}",
        created_at=created_at,
        acknowledged_at=created_at if acknowledged else None,
    )
    db.add(alert)
    await db.commit()
    return alert


async def test_the_endpoint_puts_critical_first_then_the_newest(db_session):
    promotion = await _promo(db_session)
    await _seed_alert(db_session, promotion, priority="INFO", created_at=NOW)
    await _seed_alert(db_session, promotion, priority="MEDIUM", created_at=NOW)
    await _seed_alert(
        db_session, promotion, priority="CRITICAL", created_at=NOW - timedelta(hours=10)
    )
    await _seed_alert(db_session, promotion, priority="HIGH", created_at=NOW)

    rows = await list_campaign_alerts(limit=20, response=Response(), db=db_session)

    # An old CRITICAL outranks a fresh INFO: the strip is read by urgency.
    assert [r.priority for r in rows] == ["CRITICAL", "HIGH", "MEDIUM", "INFO"]


async def test_the_endpoint_breaks_priority_ties_by_recency(db_session):
    promotion = await _promo(db_session)
    await _seed_alert(
        db_session, promotion, priority="HIGH", created_at=NOW - timedelta(hours=5)
    )
    newest = await _seed_alert(db_session, promotion, priority="HIGH", created_at=NOW)

    rows = await list_campaign_alerts(limit=20, response=Response(), db=db_session)
    assert rows[0].id == newest.id


async def test_the_endpoint_hides_acknowledged_alerts(db_session):
    promotion = await _promo(db_session)
    await _seed_alert(db_session, promotion, priority="HIGH", created_at=NOW, acknowledged=True)
    await _seed_alert(db_session, promotion, priority="INFO", created_at=NOW)

    rows = await list_campaign_alerts(limit=20, response=Response(), db=db_session)
    assert [r.priority for r in rows] == ["INFO"]


async def test_the_endpoint_honours_the_limit(db_session):
    promotion = await _promo(db_session)
    for _ in range(5):
        await _seed_alert(db_session, promotion, priority="MEDIUM", created_at=NOW)

    rows = await list_campaign_alerts(limit=2, response=Response(), db=db_session)
    assert len(rows) == 2


async def test_the_endpoint_returns_the_contract_the_frontend_codes_against(db_session):
    promotion = await _promo(db_session, airline_name="Qatar Airways")
    await _seed_alert(db_session, promotion, priority="CRITICAL", created_at=NOW)

    rows = await list_campaign_alerts(limit=20, response=Response(), db=db_session)

    payload = rows[0].model_dump()
    assert set(payload) == {
        "id",
        "promotion_id",
        "alert_type",
        "priority",
        "title_tr",
        "detail_json",
        "created_at",
    }
    assert payload["promotion_id"] == promotion.id
    assert payload["detail_json"]["airline_name"] == "Qatar Airways"


# --- the daily mail's Kampanya Radarı --------------------------------------


async def test_the_mail_section_takes_only_the_loud_unread_alerts(db_session):
    promotion = await _promo(db_session, airline_name="Qatar Airways")
    await _seed_alert(db_session, promotion, priority="CRITICAL", created_at=NOW)
    await _seed_alert(db_session, promotion, priority="HIGH", created_at=NOW)
    await _seed_alert(db_session, promotion, priority="MEDIUM", created_at=NOW)
    await _seed_alert(
        db_session, promotion, priority="HIGH", created_at=NOW, acknowledged=True
    )
    await _seed_alert(
        db_session, promotion, priority="CRITICAL", created_at=NOW - timedelta(days=3)
    )

    items = await recent_alert_highlights(db_session, now=NOW)

    assert [item["priority"] for item in items] == ["CRITICAL", "HIGH"]
    assert items[0]["priority_label"] == "Kritik"
    assert items[0]["airline_name"] == "Qatar Airways"


async def test_the_mail_renders_the_radar_when_there_is_something_to_say(db_session):
    from app.tests.test_email_render import _make_edition

    edition = await _make_edition(db_session)
    html = render_newsletter_html(
        edition,
        alerts=[
            {
                "title_tr": "Qatar Airways kampanyasında satış bitişi değişti: 31 Ekim 2026 → 15 Kasım 2026",
                "priority": "CRITICAL",
                "priority_label": "Kritik",
                "airline_name": "Qatar Airways",
                "airline_code": "QR",
            }
        ],
    )

    assert "Kampanya Radarı" in html
    assert "Kritik" in html
    assert "satış bitişi değişti" in html
    assert "/kampanyalar" in html
    # Raw enum values are internal; a reader sees the Turkish label only.
    assert "CRITICAL" not in html


async def test_the_mail_omits_the_radar_on_a_quiet_day(db_session):
    from app.tests.test_email_render import _make_edition

    edition = await _make_edition(db_session)
    assert "Kampanya Radarı" not in render_newsletter_html(edition, alerts=[])
    assert "Kampanya Radarı" not in render_newsletter_html(edition)
