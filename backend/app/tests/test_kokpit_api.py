from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from app.api.v1 import kokpit
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.services import kpi_service


def test_delta_pct_is_none_without_a_prior_reading():
    assert kokpit._delta_pct(48.0, None) is None


def test_delta_pct_is_none_when_prior_is_zero():
    assert kokpit._delta_pct(48.0, 0.0) is None


def test_delta_pct_computes_signed_percent_change():
    assert kokpit._delta_pct(110.0, 100.0) == 10.0
    assert kokpit._delta_pct(90.0, 100.0) == -10.0


async def test_fx_board_includes_the_sar_peg_and_a_live_pair(db_session):
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    repo.record("fx_usd_try", 48.11, "TRY", "Yahoo Finance (TRY=X)", False, now, "https://finance.yahoo.com/quote/TRY=X")
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    assert board.peg.currency_pair == "USD/SAR"
    assert board.peg.value == 3.75
    assert len(board.pairs) == 1
    assert board.pairs[0].currency_pair == "USD/TRY"
    assert board.pairs[0].value == 48.11
    # No 24h-old reading in the fixture yet -- honest "not enough history",
    # never a fabricated 0%.
    assert board.pairs[0].day_delta_pct is None


async def test_fx_board_computes_day_delta_against_a_reading_a_day_ago(db_session):
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    repo.record(
        "fx_usd_try", 47.0, "TRY", "Yahoo Finance (TRY=X)", False, now - timedelta(days=1, minutes=5),
        "https://finance.yahoo.com/quote/TRY=X",
    )
    repo.record(
        "fx_usd_try", 48.0, "TRY", "Yahoo Finance (TRY=X)", False, now, "https://finance.yahoo.com/quote/TRY=X"
    )
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    pair = next(p for p in board.pairs if p.currency_pair == "USD/TRY")
    assert pair.day_delta_pct == round((48.0 - 47.0) / 47.0 * 100, 2)


async def test_fx_board_skips_pairs_with_no_observations_yet(db_session):
    board = await kokpit.get_fx_board(Response(), db_session)
    assert board.pairs == []
    assert board.peg.currency_pair == "USD/SAR"  # the peg always shows, live data or not


async def test_get_fx_forecasts_filters_by_pair(db_session):
    repo = CuratedRepository(db_session)
    await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=date(2026, 8, 21),
        source_url="https://danske",
    )
    await repo.upsert_fx_forecast(
        institution="ING",
        currency_pair="EUR/USD",
        horizon_label="Q4 2026",
        horizon_months=None,
        value=1.22,
        publication_date=date(2025, 11, 10),
        source_url="https://ing",
    )
    await db_session.commit()

    out = await kokpit.get_fx_forecasts(Response(), pair="USD/TRY", horizon_months=None, db=db_session)
    assert [row.institution for row in out] == ["Danske Bank"]


async def test_fx_board_carries_the_pairs_the_market_strip_expects(db_session):
    """Kokpit's compact strip prints one card per live pair, EUR/TRY and
    GBP/USD included. A pair missing from LIVE_FX_PAIRS or from the label map
    would leave a card that can never fill in."""
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    for metric_key, symbol, _base, _quote, unit in kpi_service.LIVE_FX_PAIRS:
        repo.record(
            metric_key, 1.5, unit, f"Yahoo Finance ({symbol})", False, now,
            f"https://finance.yahoo.com/quote/{symbol}",
        )
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    names = [pair.currency_pair for pair in board.pairs]
    assert "EUR/TRY" in names
    assert "GBP/USD" in names
    # The seventh pair Kokpit's FX board asks for. Its table row is
    # data-driven, so before this pair existed the row simply did not appear.
    assert "GBP/TRY" in names
    assert len(names) == len(kpi_service.LIVE_FX_PAIRS)
    # No metric_key ever leaks through as a display name.
    assert all(not name.startswith("fx_") for name in names)


async def test_a_brand_new_pair_reports_no_deltas_rather_than_zero(db_session):
    """EUR/TRY and GBP/USD start with a single reading. Until the 15-minute
    cron has run for a day, every delta must be None -- the UI turns that into
    "yeterli geçmiş yok", and a 0% there would be a fabrication."""
    repo = KpiRepository(db_session)
    repo.record(
        "fx_eur_try", 56.09, "TRY", "Yahoo Finance (EURTRY=X)", False,
        datetime.now(timezone.utc), "https://finance.yahoo.com/quote/EURTRY=X",
    )
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    pair = next(p for p in board.pairs if p.currency_pair == "EUR/TRY")
    assert pair.day_delta_pct is None
    assert pair.week_delta_pct is None
    assert pair.month_delta_pct is None
    assert pair.sparkline == [56.09]


# --- forecast target dates ------------------------------------------------
# The mapping from an institution's own horizon wording to a plotting
# coordinate. `horizon_label` itself is never rewritten -- these assertions are
# about the SEPARATE derived field, and every one of them checks that the
# derivation announces itself in `target_date_basis_tr`.


def test_explicit_month_horizon_is_added_to_the_publication_date():
    target, basis = kokpit.forecast_target_date(
        horizon_months=3, horizon_label="+3m", publication_date=date(2026, 8, 21)
    )
    assert target == date(2026, 11, 21)
    assert "+3m" in basis


def test_month_horizon_clamps_to_the_end_of_a_shorter_month():
    """31 Aug + 6m is the end of February, not the 3rd of March."""
    target, _ = kokpit.forecast_target_date(
        horizon_months=6, horizon_label="+6m", publication_date=date(2026, 8, 31)
    )
    assert target == date(2027, 2, 28)


def test_end_of_year_label_maps_to_31_december_of_that_year():
    target, basis = kokpit.forecast_target_date(
        horizon_months=None, horizon_label="end-2026", publication_date=date(2026, 7, 13)
    )
    assert target == date(2026, 12, 31)
    assert "31 Aralık 2026" in basis


def test_year_end_label_uses_the_publication_year_not_a_later_one():
    target, basis = kokpit.forecast_target_date(
        horizon_months=None, horizon_label="year-end", publication_date=date(2026, 6, 25)
    )
    assert target == date(2026, 12, 31)
    assert "2026" in basis


def test_quarter_label_maps_to_the_quarters_midpoint():
    """A quarter is a span. The midpoint at least says so; either edge would
    claim a precision the institution did not publish."""
    for label, expected in (
        ("Q1 2027", date(2027, 2, 15)),
        ("Q2 2027", date(2027, 5, 15)),
        ("Q3 2027", date(2027, 8, 15)),
        ("Q4 2026", date(2026, 11, 15)),
    ):
        target, basis = kokpit.forecast_target_date(
            horizon_months=None, horizon_label=label, publication_date=date(2025, 11, 10)
        )
        assert target == expected
        assert "orta nokta" in basis


def test_an_unmappable_horizon_gets_no_date_and_no_basis():
    """Nothing is guessed. The row keeps its place in the table and simply has
    no marker on the chart."""
    target, basis = kokpit.forecast_target_date(
        horizon_months=None, horizon_label="önümüzdeki dönem", publication_date=date(2026, 1, 1)
    )
    assert target is None
    assert basis is None


async def test_fx_forecasts_endpoint_attaches_the_derived_target_date(db_session):
    repo = CuratedRepository(db_session)
    await repo.upsert_fx_forecast(
        institution="Garanti BBVA Yatırım",
        currency_pair="USD/TRY",
        horizon_label="year-end",
        horizon_months=None,
        value=52.0,
        publication_date=date(2026, 6, 25),
        source_url="https://example.test/garanti",
    )
    await db_session.commit()

    out = await kokpit.get_fx_forecasts(Response(), pair=None, horizon_months=None, db=db_session)

    row = out[0]
    assert row.target_date == date(2026, 12, 31)
    assert row.target_date_basis_tr is not None
    # The institution's own wording is untouched -- the derived date is an
    # extra field beside it, never a replacement for it.
    assert row.horizon_label == "year-end"


async def test_get_iata_indicators_filters_by_kind(db_session):
    repo = CuratedRepository(db_session)
    await repo.upsert_iata_indicator(
        metric="load_factor",
        kind="actual",
        value=83.5,
        unit="%",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_label_tr="2025",
        publication_date=date(2026, 6, 7),
        source_url="https://iata.org",
    )
    await db_session.commit()

    actual = await kokpit.get_iata_indicators(Response(), kind="actual", region=None, db=db_session)
    forecast = await kokpit.get_iata_indicators(Response(), kind="forecast", region=None, db=db_session)
    assert len(actual) == 1
    assert forecast == []


async def test_get_market_pulse_raises_404_when_none_generated_yet(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await kokpit.get_market_pulse(Response(), db_session)
    assert exc_info.value.status_code == 404


async def test_get_market_pulse_returns_the_latest_pulse(db_session):
    repo = MarketPulseRepository(db_session)
    repo.record(
        "USD/TRY sakin seyrediyor.",
        [{"claim": "USD/TRY 48.1", "source": "Yahoo Finance", "source_url": "https://x"}],
        datetime.now(timezone.utc),
    )
    await db_session.commit()

    out = await kokpit.get_market_pulse(Response(), db_session)
    assert out.summary_tr == "USD/TRY sakin seyrediyor."
    assert out.citations[0].source == "Yahoo Finance"
