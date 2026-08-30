"""GET /kokpit/annual-series -- the 2019-2026 IATA industry series behind
Kokpit's sector chart and KPI strip.

The endpoint reads the same rows historical_seed.py writes, so these tests seed
through that module rather than hand-rolling fixtures: a test that invented its
own annual points could pass while the real seed produced a shape the chart
cannot draw.
"""
from datetime import datetime, timezone

from fastapi import Response

from app.api.v1 import kokpit
from app.ingest.historical_seed import YEARS, seed_kpi_history
from app.repositories.kpi_repository import KpiRepository


async def test_annual_series_returns_one_point_per_published_year(db_session):
    await seed_kpi_history(db_session)

    board = await kokpit.get_annual_series(Response(), db_session)

    by_key = {series.metric_key: series for series in board.series}
    # Every metric the chart and the strip name must actually be there.
    assert set(by_key) == {key for key, _, _ in kokpit.ANNUAL_METRICS}
    for series in board.series:
        assert [point.year for point in series.points] == list(YEARS)


async def test_annual_series_marks_the_forecast_tail_honestly(db_session):
    await seed_kpi_history(db_session)

    board = await kokpit.get_annual_series(Response(), db_session)
    rpk = next(series for series in board.series if series.metric_key == "rpk")
    kinds = {point.year: point.kind for point in rpk.points}

    assert kinds[2019] == "actual"
    assert kinds[2024] == "actual"
    # IATA's June 2026 report publishes 2025 as an estimate and 2026 as a
    # forecast -- the chart draws both dashed, so both must be flagged.
    assert kinds[2025] == "estimate"
    assert kinds[2026] == "forecast"


async def test_annual_series_carries_the_scope_caveat_and_one_attribution(db_session):
    await seed_kpi_history(db_session)

    board = await kokpit.get_annual_series(Response(), db_session)

    # Nothing here is THY's own, and nothing here is monthly. The payload says
    # so, so no surface can render these numbers as company figures.
    assert "sektör geneli" in board.scope_tr
    assert "yıllık" in board.scope_tr
    assert board.source.startswith("IATA")
    assert board.source_url.startswith("https://www.iata.org/")


async def test_annual_series_keeps_the_full_span_after_an_iata_revision(db_session):
    """A revised 2026 figure adds a row, it does not cost the chart its 2019."""
    await seed_kpi_history(db_session)
    repo = KpiRepository(db_session)
    repo.record(
        "rpk",
        9_800_000_000_000.0,
        "RPK",
        "IATA Küresel Görünüm (revize)",
        True,
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()

    board = await kokpit.get_annual_series(Response(), db_session)
    rpk = next(series for series in board.series if series.metric_key == "rpk")

    assert [point.year for point in rpk.points] == list(YEARS)
    # Newest row for the year wins.
    assert rpk.points[-1].value == 9_800_000_000_000.0


async def test_annual_series_is_empty_rather_than_fabricated_before_seeding(db_session):
    board = await kokpit.get_annual_series(Response(), db_session)
    assert board.series == []


def test_year_kind_is_derived_from_the_report_not_hardcoded():
    assert kokpit.FORECAST_YEAR == kokpit.IATA_PUBLISHED_AT.year
    assert kokpit.ESTIMATE_YEAR == kokpit.FORECAST_YEAR - 1
    assert kokpit._year_kind(kokpit.FORECAST_YEAR + 1) == "forecast"


def test_every_annual_metric_has_a_label_short_enough_for_a_strip_cell():
    for _, label, _ in kokpit.ANNUAL_METRICS:
        assert label
        assert len(label) <= 16, f"{label!r} will not fit a KPI strip cell"
