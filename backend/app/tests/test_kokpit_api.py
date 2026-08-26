from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from app.api.v1 import kokpit
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository


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
