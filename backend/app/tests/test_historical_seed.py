"""The seeded history is transcribed from IATA's June 2026 Global Outlook, and
four of its metrics (ASK, yield, RASK, CASK) are arithmetic on that transcription
rather than rows we can copy. IATA states those results independently elsewhere
in the same report, so these tests check our arithmetic against its published
figures -- if a transcription digit is wrong, the cross-checks stop agreeing.
"""
import pytest

from app.ingest.historical_seed import (
    PUBLISHED_AT,
    YEARS,
    build_points,
    seed_kpi_history,
)


def _value(metric_key: str, year: int) -> float:
    year_index = YEARS.index(year)
    from app.ingest.historical_seed import _as_of

    as_of = _as_of(YEARS[year_index])
    for point in build_points():
        if point.metric_key == metric_key and point.as_of == as_of:
            return point.value
    raise AssertionError(f"no seed point for {metric_key} {year}")


def test_derived_2026_yield_matches_iatas_published_yoy_change():
    # IATA publishes "passenger ticket yield +7.0% YoY" for 2026 but no absolute
    # value; ours is derived from revenue/RPK. The two must agree.
    yield_2025 = _value("yield_per_rpk", 2025)
    yield_2026 = _value("yield_per_rpk", 2026)

    assert yield_2026 / yield_2025 == pytest.approx(1.07, abs=0.005)


def test_derived_2026_total_expenses_match_iatas_published_cost_breakdown():
    # IATA states 2026 fuel costs $350bn + non-fuel $767bn = $1,117bn. Our CASK
    # is derived from (revenue - EBIT), which must land on the same total.
    cask_cents = _value("cask", 2026)
    ask = _value("ask", 2026)
    derived_expenses_bn = cask_cents / 100 * ask / 1_000_000_000

    assert derived_expenses_bn == pytest.approx(1117, abs=5)


def test_derived_2026_total_revenue_matches_iatas_headline_figure():
    # IATA's headline: "total industry revenues expected to reach $1.165 trillion".
    rask_cents = _value("rask", 2026)
    ask = _value("ask", 2026)
    derived_revenue_bn = rask_cents / 100 * ask / 1_000_000_000

    assert derived_revenue_bn == pytest.approx(1165, abs=5)


def test_derived_ask_reproduces_the_load_factor_identity():
    # Load factor is defined as RPK/ASK, so the derivation must round-trip.
    rpk = _value("rpk", 2026)
    ask = _value("ask", 2026)
    load_factor = _value("load_factor", 2026)

    assert rpk / ask * 100 == pytest.approx(load_factor, abs=0.05)


def test_aviation_revenue_is_passenger_plus_ancillary():
    total = _value("total_aviation_revenue_ytd", 2026)
    passenger = _value("passenger_revenue_ytd", 2026)
    ancillary = _value("ancillary_revenue_ytd", 2026)

    assert total == passenger + ancillary


def test_covid_collapse_survived_transcription():
    # A sanity check on the shape of the series: 2020 must be the trough.
    load_factors = [_value("load_factor", year) for year in YEARS]
    assert min(load_factors) == _value("load_factor", 2020)
    assert _value("load_factor", 2020) == 65.2


async def test_seeding_is_idempotent(db_session):
    first = await seed_kpi_history(db_session)
    second = await seed_kpi_history(db_session)

    assert first > 0
    # Re-running the maintenance job must not duplicate published history.
    assert second == 0


async def test_seeded_points_carry_a_citation(db_session):
    from sqlalchemy import select

    from app.models.kpi import KPI

    await seed_kpi_history(db_session)

    rows = (await db_session.execute(select(KPI).where(KPI.metric_key == "rask"))).scalars().all()
    assert rows
    for row in rows:
        assert "IATA" in row.source
        assert row.source_url.startswith("https://www.iata.org/")
        assert row.is_estimate is True  # published figure, not a live reading


async def test_current_forecast_is_the_latest_point(db_session):
    from app.repositories.kpi_repository import KpiRepository

    await seed_kpi_history(db_session)

    latest = await KpiRepository(db_session).latest("load_factor")
    assert latest.as_of == PUBLISHED_AT
    assert latest.value == 84.0
