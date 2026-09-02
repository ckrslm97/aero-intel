"""GET /events: the computed fields, the new filters, and the guarantee that
the call the calendar page already makes still returns exactly what it did.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import events as events_api
from app.core.db import get_db
from app.models.event import AviationEvent
from app.services.event_scoring import event_importance


def _today() -> date:
    return datetime.now(timezone.utc).date()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(events_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _event(
    name: str,
    *,
    city: str = "Münih",
    region: str = "europe",
    starts: date | None = None,
    length: int = 3,
    impact: str = "high",
    attendance: int | None = 50_000,
    event_type: str = "conference",
) -> AviationEvent:
    starts = starts or _today() + timedelta(days=30)
    return AviationEvent(
        name=name,
        starts=starts,
        ends=starts + timedelta(days=length - 1),
        city=city,
        country="Almanya",
        region=region,
        url=f"https://example.test/{name.replace(' ', '-').lower()}",
        summary_tr="Özet.",
        event_type=event_type,
        impact_level=impact,
        attendance=attendance,
        demand_effect_tr="Talep etkisi.",
    )


@pytest.fixture
async def calendar(db_session):
    rows = [
        _event("Yakin Buyuk", city="Münih", starts=_today() + timedelta(days=10),
               impact="high", attendance=300_000, length=3),
        _event("Uzak Kucuk", city="Londra", starts=_today() + timedelta(days=320),
               impact="low", attendance=2_000, length=120, event_type="festival"),
        _event("Sayimsiz", city="Çin geneli", region="asia",
               starts=_today() + timedelta(days=60), impact="medium", attendance=None),
        _event("Orta", city="Paris", starts=_today() + timedelta(days=120),
               impact="medium", attendance=40_000, event_type="airshow"),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.flush()
    return rows


# --- the computed fields --------------------------------------------------

async def test_events_carry_the_airports_their_city_actually_flies_through(client, calendar):
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    by_name = {row["name"]: row for row in body}
    assert by_name["Yakin Buyuk"]["relevant_airports"] == ["MUC"]
    assert by_name["Uzak Kucuk"]["relevant_airports"] == ["LHR", "LGW", "STN", "LTN", "LCY"]
    # Paris is the one automatic resolution got most obviously wrong.
    assert by_name["Orta"]["relevant_airports"] == ["CDG", "ORY"]


async def test_a_scope_that_is_not_a_city_serialises_as_an_empty_list(client, calendar):
    """Not null and not a guessed gateway -- "Çin geneli" has no airport."""
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    row = next(r for r in body if r["name"] == "Sayimsiz")
    assert row["relevant_airports"] == []


async def test_an_event_without_a_headcount_serialises_a_null_score(client, calendar):
    """null means "not measurable". A zero here would tell the UI this event is
    small, which is the opposite of what a missing headcount usually means."""
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    by_name = {row["name"]: row for row in body}
    assert by_name["Sayimsiz"]["importance_score"] is None
    assert by_name["Yakin Buyuk"]["importance_score"] is not None
    assert 0.0 <= by_name["Yakin Buyuk"]["importance_score"] <= 1.0


async def test_the_serialised_score_matches_the_service(client, calendar):
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    by_name = {row["name"]: row for row in body}
    for event in calendar:
        expected = event_importance(
            event.impact_level, event.attendance, event.starts, event.ends, _today()
        )
        assert by_name[event.name]["importance_score"] == expected


async def test_days_until_is_signed_for_an_event_already_running(client, db_session):
    """The calendar filters on `ends`, so an in-progress event stays on it. Its
    days_until has to say it started, not that it is unknown."""
    started = _event("Suren", starts=_today() - timedelta(days=2), length=6)
    db_session.add(started)
    await db_session.flush()
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    assert body[0]["days_until"] == -2


async def test_the_existing_fields_are_untouched(client, calendar):
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    row = next(r for r in body if r["name"] == "Yakin Buyuk")
    assert set(row) == {
        "id", "name", "starts", "ends", "city", "country", "region", "url",
        "summary_tr", "event_type", "impact_level", "attendance",
        "demand_effect_tr", "date_range_tr",
        "relevant_airports", "importance_score", "days_until",
    }
    assert row["date_range_tr"]


# --- validation -----------------------------------------------------------

async def test_an_unknown_region_is_rejected_rather_than_silently_empty(client, calendar):
    """It used to return 200 and an empty calendar. A typo that looks like "no
    events this quarter" is the worst failure a calendar can have."""
    async with client as http:
        response = await http.get("/api/v1/events", params={"region": "erupoe"})
    assert response.status_code == 422


async def test_an_unknown_event_type_is_rejected_too(client, calendar):
    """`Query(..., enum=[...])` only decorated the OpenAPI schema; FastAPI never
    enforced it, so this used to be a 200 as well."""
    async with client as http:
        response = await http.get("/api/v1/events", params={"event_type": "airshoww"})
    assert response.status_code == 422


async def test_valid_taxonomy_regions_are_accepted(client, calendar):
    async with client as http:
        response = await http.get("/api/v1/events", params={"region": "europe"})
    assert response.status_code == 200
    assert {row["region"] for row in response.json()} == {"europe"}


@pytest.mark.parametrize("bad", [{"min_impact": "huge"}, {"order": "size"}, {"limit": 0}])
async def test_out_of_vocabulary_parameters_are_rejected(client, calendar, bad):
    async with client as http:
        assert (await http.get("/api/v1/events", params=bad)).status_code == 422


async def test_the_limit_has_a_ceiling(client, calendar):
    async with client as http:
        assert (await http.get(
            "/api/v1/events", params={"limit": events_api.MAX_LIMIT + 1}
        )).status_code == 422


# --- the new filters ------------------------------------------------------

async def test_min_impact_means_at_least_this_hard_hitting(client, calendar):
    """impact_level is a rank, not a category: asking for "medium" must not
    hide the events that hit harder than medium."""
    async with client as http:
        high = (await http.get("/api/v1/events", params={"min_impact": "high"})).json()
        medium = (await http.get("/api/v1/events", params={"min_impact": "medium"})).json()
        low = (await http.get("/api/v1/events", params={"min_impact": "low"})).json()
    assert {r["impact_level"] for r in high} == {"high"}
    assert {r["impact_level"] for r in medium} == {"high", "medium"}
    assert len(low) == len(calendar)


async def test_limit_caps_the_calendar_without_reordering_it(client, calendar):
    async with client as http:
        full = (await http.get("/api/v1/events")).json()
        capped = (await http.get("/api/v1/events", params={"limit": 2})).json()
    assert len(capped) == 2
    assert [r["name"] for r in capped] == [r["name"] for r in full[:2]]


async def test_order_by_importance_ranks_the_scorable_events_first(client, calendar):
    async with client as http:
        ranked = (await http.get("/api/v1/events", params={"order": "importance"})).json()
    scores = [r["importance_score"] for r in ranked if r["importance_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0]["name"] == "Yakin Buyuk"


async def test_unscorable_events_sort_last_rather_than_as_zero(client, calendar):
    """They are not small, they are not comparable. Anywhere but the end would
    assert something about them that the data does not say."""
    async with client as http:
        ranked = (await http.get("/api/v1/events", params={"order": "importance"})).json()
    assert ranked[-1]["importance_score"] is None
    assert ranked[-1]["name"] == "Sayimsiz"


async def test_the_importance_limit_is_applied_after_ranking(client, calendar):
    """Pushing LIMIT into SQL here would return the two earliest events and
    then rank those two -- a different answer."""
    async with client as http:
        top = (await http.get(
            "/api/v1/events", params={"order": "importance", "limit": 2}
        )).json()
        ranked = (await http.get("/api/v1/events", params={"order": "importance"})).json()
    assert [r["name"] for r in top] == [r["name"] for r in ranked[:2]]


# --- the regression the redesign must not cause ---------------------------

async def test_the_default_call_is_byte_for_byte_what_it_was(client, calendar):
    """The calendar page calls GET /events with no parameters. Unlimited, in
    start-date order, every event -- the new parameters are additive."""
    async with client as http:
        body = (await http.get("/api/v1/events")).json()
    assert len(body) == len(calendar)
    starts = [row["starts"] for row in body]
    assert starts == sorted(starts)
    assert [row["name"] for row in body] == [
        "Yakin Buyuk", "Sayimsiz", "Orta", "Uzak Kucuk"
    ]


async def test_the_existing_filters_still_behave(client, calendar):
    async with client as http:
        by_type = (await http.get("/api/v1/events", params={"event_type": "airshow"})).json()
        # date_from filters on `ends`, so an event still in progress stays.
        upcoming = (await http.get(
            "/api/v1/events",
            params={"date_from": (_today() + timedelta(days=100)).isoformat()},
        )).json()
    assert [row["name"] for row in by_type] == ["Orta"]
    assert {row["name"] for row in upcoming} == {"Orta", "Uzak Kucuk"}
