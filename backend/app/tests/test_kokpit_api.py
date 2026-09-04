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


async def test_fx_board_refuses_a_delta_when_the_window_never_closed(db_session):
    """A stale board must say "no measurement", not "no movement".

    `closest_before` answers with the newest row at or before the cutoff, so
    when the cron has been down for two days the row it returns for "one day
    ago" IS the latest row. Dividing that value by itself published a
    confident 0.0, and the FX table rendered "%0,0" in the 1G column of every
    pair -- eight claims that the lira had not moved in a day, made by a board
    that had not been read in two. Its own 1H column said "—" on the same row.
    """
    repo = KpiRepository(db_session)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    repo.record(
        "fx_usd_try", 48.25, "TRY", "Yahoo Finance (TRY=X)", False, two_days_ago,
        "https://finance.yahoo.com/quote/TRY=X",
    )
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    pair = next(p for p in board.pairs if p.currency_pair == "USD/TRY")
    assert pair.value == 48.25  # the reading itself is real and still shown
    assert pair.day_delta_pct is None
    assert pair.week_delta_pct is None
    assert pair.month_delta_pct is None


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


# --- the FX board's query budget ------------------------------------------
#
# Vercel gives this endpoint 30 seconds and Neon is a network hop away, so what
# matters here is the NUMBER of round trips, not their individual cost. The
# board used to spend five per pair -- latest, trend, and one closest_before
# for each of the three delta windows -- which was 40 sequential queries for
# the eight pairs LIVE_FX_PAIRS carries, and grew by five every time a pair was
# added. The two tests below fix both halves of that: a ceiling, and the fact
# that the ceiling does not move when the pair list does.


def _record_pair(repo, metric_key: str, now):
    """One pair with enough history for all three delta windows to close."""
    for days_ago in (40, 20, 5, 0):
        repo.record(
            metric_key,
            40.0 + days_ago,
            "TRY",
            "Yahoo Finance",
            False,
            now - timedelta(days=days_ago),
            "https://finance.yahoo.com/",
        )


async def test_fx_board_costs_four_queries_however_many_pairs_there_are(
    db_session, query_counter
):
    """One trends_for plus one closest_before_many per delta window. Four."""
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    for metric_key, *_rest in kpi_service.LIVE_FX_PAIRS:
        _record_pair(repo, metric_key, now)
    await db_session.commit()

    with query_counter() as counted:
        board = await kokpit.get_fx_board(Response(), db_session)

    assert len(board.pairs) == len(kpi_service.LIVE_FX_PAIRS)
    assert counted.count == 4


async def test_fx_board_query_count_does_not_grow_with_the_pair_list(
    db_session, query_counter
):
    """The negative half, and the one that actually guards the regression: a
    board with one pair and a board with all of them cost the same. Asserting
    only the ceiling above would still pass a per-pair implementation whose
    fixture happened to seed four pairs."""
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    _record_pair(repo, kpi_service.LIVE_FX_PAIRS[0][0], now)
    await db_session.commit()

    with query_counter() as one_pair:
        first = await kokpit.get_fx_board(Response(), db_session)

    for metric_key, *_rest in kpi_service.LIVE_FX_PAIRS[1:]:
        _record_pair(repo, metric_key, now)
    await db_session.commit()

    with query_counter() as every_pair:
        full = await kokpit.get_fx_board(Response(), db_session)

    assert len(first.pairs) == 1
    assert len(full.pairs) == len(kpi_service.LIVE_FX_PAIRS)
    assert one_pair.count == every_pair.count


async def test_batched_deltas_match_the_per_pair_answers(db_session):
    """The batch must not change a single published number.

    `closest_before_many` replaced eight calls to `closest_before`; this asserts
    the two answer identically, pair by pair, against the same fixture -- an
    optimisation that quietly shifts a delta is not an optimisation.
    """
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    for metric_key, *_rest in kpi_service.LIVE_FX_PAIRS[:3]:
        _record_pair(repo, metric_key, now)
    await db_session.commit()

    board = await kokpit.get_fx_board(Response(), db_session)

    for pair in board.pairs:
        metric_key = next(
            key for key, label in kpi_service.FX_PAIR_LABELS.items()
            if label == pair.currency_pair
        )
        latest = await repo.latest(metric_key)
        for delta, days in (
            (pair.day_delta_pct, 1),
            (pair.week_delta_pct, 7),
            (pair.month_delta_pct, 30),
        ):
            prior = await repo.closest_before(metric_key, now - timedelta(days=days))
            assert delta == kokpit._window_delta(latest, prior)
        assert pair.sparkline == [row.value for row in await repo.trend(metric_key, points=48)]


async def test_closest_before_many_omits_a_metric_with_no_earlier_reading(db_session):
    """Absence, never a substitute. A pair whose only reading is newer than the
    cutoff must be MISSING from the batch result, so `_window_delta` sees None
    and the board prints "—" -- the same refusal the single-key version makes,
    and the reason the 1G column cannot fabricate a %0,0 on a stale board."""
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    repo.record("fx_usd_try", 48.0, "TRY", "Yahoo", False, now - timedelta(days=10), "u")
    repo.record("fx_eur_try", 56.0, "TRY", "Yahoo", False, now, "u")
    await db_session.commit()

    found = await repo.closest_before_many(
        ["fx_usd_try", "fx_eur_try"], now - timedelta(days=7)
    )

    assert set(found) == {"fx_usd_try"}
    assert found["fx_usd_try"].value == 48.0

    board = await kokpit.get_fx_board(Response(), db_session)
    eur = next(p for p in board.pairs if p.currency_pair == "EUR/TRY")
    assert eur.week_delta_pct is None


async def test_closest_before_many_picks_the_newest_row_at_or_before_the_cutoff(db_session):
    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    for days_ago, value in ((30, 40.0), (9, 44.0), (8, 45.0), (2, 47.0)):
        repo.record("fx_usd_try", value, "TRY", "Yahoo", False, now - timedelta(days=days_ago), "u")
    await db_session.commit()

    found = await repo.closest_before_many(["fx_usd_try"], now - timedelta(days=7))

    # 45.0 (8 days ago), not 47.0 (inside the window) and not 44.0 (older).
    assert found["fx_usd_try"].value == 45.0
