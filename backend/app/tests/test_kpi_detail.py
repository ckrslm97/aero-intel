"""GET /api/v1/kpis/{metric_key} -- what the detail page is allowed to claim.

Three separate claims, all of which the endpoint used to make without having
earned them:

* **What period the value describes.** `/kpi/load_factor` serves IATA's 2026
  full-year forecast and the page drew it exactly like Brent's last trade:
  one number, one timestamp, no period. A projection for a year with four
  months left to run read as this morning's measurement.
* **What the delta means.** A load factor moving 83.0 -> 83.4 rose 0.4 POINTS.
  The percent form (0.48) is arithmetically true and is not what anyone in
  revenue management means, so printing it behind a `%` states a number nobody
  would recognise under the unit they do.
* **Whether a cross-check happened at all.** Two readings were badged
  "Eşleşiyor" without their timestamps ever being compared, and a comparison
  that could not be computed fell through to 0.0 -- the strongest possible
  agreement -- so the one case where we knew nothing rendered as the case
  where we were surest.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import kpis as kpis_api
from app.core.db import get_db
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kpi import (
    CORROBORATION_DIVERGES,
    CORROBORATION_INCOMPARABLE,
    CORROBORATION_MATCH,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
LY_DATE = datetime(2025, 12, 31, tzinfo=timezone.utc)


@pytest.fixture
def kpi_app(db_session):
    app = FastAPI()
    app.include_router(kpis_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


async def _detail(app: FastAPI, metric_key: str) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/kpis/{metric_key}")
    assert response.status_code == 200, response.text
    return response.json()


# --- what period the value describes ---------------------------------------


async def test_an_annual_forecast_says_which_year_and_that_it_is_a_forecast(
    kpi_app, db_session
):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 83.0, "%", "IATA", True, LY_DATE)
    repo.record("load_factor", 83.4, "%", "IATA", True, NOW)
    await db_session.commit()

    detail = await _detail(kpi_app, "load_factor")

    assert detail["period_label"] == "2026 · tahmin"
    # And the delta is labelled with what it is actually measured against --
    # the previous stored row here IS last year, not the previous quarter-hour.
    assert detail["comparison_label"] == "2025'e göre"
    # Points, not percent. 0.48 is the percent form and must not appear.
    assert detail["delta_points"] == 0.4
    assert detail["delta_pct"] is None


async def test_a_live_reading_is_not_dressed_up_as_a_period_claim(kpi_app, db_session):
    """The negative half: a metric read from a live source must not be
    labelled "2026 · tahmin" merely because its timestamp falls in a year the
    IATA report treats as a forecast."""
    repo = KpiRepository(db_session)
    repo.record("flights_airborne", 11_000, "uçuş", "OpenSky Network", False, NOW - timedelta(hours=1))
    repo.record("flights_airborne", 12_000, "uçuş", "OpenSky Network", False, NOW)
    await db_session.commit()

    detail = await _detail(kpi_app, "flights_airborne")

    assert detail["period_label"] == kpis_api.LIVE_PERIOD_LABEL_TR
    assert detail["comparison_label"] == kpis_api.PREVIOUS_COMPARISON_LABEL
    # A count is not denominated in points, so the percent delta survives.
    assert detail["delta_pct"] == pytest.approx(9.09)
    assert detail["delta_points"] is None


async def test_a_metric_with_one_observation_has_no_comparison_label(kpi_app, db_session):
    """No previous reading, no delta -- and so no sentence describing one."""
    repo = KpiRepository(db_session)
    repo.record("flights_airborne", 12_000, "uçuş", "OpenSky Network", False, NOW)
    await db_session.commit()

    detail = await _detail(kpi_app, "flights_airborne")

    assert detail["delta_pct"] is None
    assert detail["delta_points"] is None
    assert detail["comparison_label"] is None


# --- cross-validation ------------------------------------------------------


async def _with_corroboration(db_session, *, value, as_of):
    repo = KpiRepository(db_session)
    repo.record("flights_airborne", 12_000, "uçuş", "OpenSky Network", False, NOW)
    repo.record(
        "flights_airborne",
        value,
        "uçuş",
        "Second Source",
        False,
        as_of,
        None,
        is_primary=False,
    )
    await db_session.commit()


async def test_two_readings_of_the_same_moment_are_called_a_match(kpi_app, db_session):
    await _with_corroboration(db_session, value=12_010, as_of=NOW)

    detail = await _detail(kpi_app, "flights_airborne")
    row = detail["corroborations"][0]

    assert row["verdict"] == CORROBORATION_MATCH
    assert row["verdict_label_tr"] == "Eşleşiyor"
    assert row["diff_pct"] == pytest.approx(0.083, abs=0.001)
    assert row["incomparable_reason"] is None
    # The rule is stated beside the verdict rather than asserted.
    assert detail["corroboration_match_pct"] == kpis_api.CORROBORATION_MATCH_PCT


async def test_two_readings_that_disagree_say_so(kpi_app, db_session):
    await _with_corroboration(db_session, value=13_500, as_of=NOW)

    row = (await _detail(kpi_app, "flights_airborne"))["corroborations"][0]

    assert row["verdict"] == CORROBORATION_DIVERGES
    assert row["diff_pct"] == pytest.approx(12.5)


async def test_a_stale_second_source_is_incomparable_not_corroborating(
    kpi_app, db_session
):
    """The bug: the two timestamps were never compared. A cross-check source
    that stopped answering hours ago sat beside today's primary and, if the
    value happened not to have moved, was badged "Eşleşiyor" -- corroboration
    asserted between a reading and a stale one."""
    await _with_corroboration(
        db_session,
        value=12_000,  # identical, which is exactly what used to make it a "match"
        as_of=NOW - kpis_api.CORROBORATION_MAX_AGE_GAP - timedelta(minutes=1),
    )

    row = (await _detail(kpi_app, "flights_airborne"))["corroborations"][0]

    assert row["verdict"] == CORROBORATION_INCOMPARABLE
    assert row["verdict_label_tr"] == "Karşılaştırılamaz"
    assert row["incomparable_reason"] == kpis_api.REASON_AS_OF_TOO_FAR_APART
    # Not 0.0. A comparison that did not happen has no number, and 0.0 is the
    # strongest agreement this scale can express.
    assert row["diff_pct"] is None
    # The reader can still see both timestamps and judge the refusal: the
    # corroboration's own as_of is on the wire next to the primary's.
    assert row["as_of"] is not None


async def test_a_reading_just_inside_the_age_gap_still_corroborates(kpi_app, db_session):
    """The negative half of the timestamp rule: scheduler jitter must not turn
    a healthy cross-check into a refusal."""
    await _with_corroboration(
        db_session,
        value=12_000,
        as_of=NOW - kpis_api.CORROBORATION_MAX_AGE_GAP + timedelta(minutes=1),
    )

    row = (await _detail(kpi_app, "flights_airborne"))["corroborations"][0]

    assert row["verdict"] == CORROBORATION_MATCH
    assert row["diff_pct"] == 0.0


# --- where the chart's history came from ------------------------------------


async def test_own_history_is_labelled_as_ours_not_as_the_sources_archive(
    kpi_app, db_session
):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 83.4, "%", "IATA", True, NOW)
    await db_session.commit()

    detail = await _detail(kpi_app, "load_factor")

    assert detail["history_provenance"] == kpis_api.OWN_HISTORY
    assert detail["history_is_external"] is False
    assert "kendi periyodik ölçümlerimizden" in detail["history_provenance_tr"]
