"""The arithmetic behind Kokpit's "Yakıt & Enerji" panel.

Every assertion here is about a number the panel PRINTS, and about the cases
where it must print nothing at all instead. The None cases carry as much
weight as the computed ones: an indicator defaulted to zero because the series
was too short is the exact failure this panel exists to avoid.
"""
import math
from datetime import datetime, timedelta, timezone

from app.services import energy_service
from app.services.energy_service import (
    MIN_VOLATILITY_RETURNS,
    TRADING_DAYS_PER_YEAR,
    annualized_volatility,
    indicators_from_history,
    pct_change,
    percentile_of,
)

BASE = datetime(2026, 8, 31, tzinfo=timezone.utc)


def series(closes: list[float], *, end: datetime = BASE) -> list[tuple[datetime, float]]:
    """Daily closes ending at `end`, oldest first -- the shape fetch_history
    returns."""
    return [
        (end - timedelta(days=len(closes) - 1 - i), close) for i, close in enumerate(closes)
    ]


# --- pct_change -----------------------------------------------------------


def test_pct_change_is_none_without_a_prior():
    assert pct_change(100.0, None) is None


def test_pct_change_is_none_against_a_zero_prior():
    """A zero prior cannot anchor a percentage; 0 and infinity are both lies."""
    assert pct_change(100.0, 0.0) is None


def test_pct_change_is_signed():
    assert pct_change(110.0, 100.0) == 10.0
    assert pct_change(90.0, 100.0) == -10.0


# --- volatility -----------------------------------------------------------


def test_volatility_is_none_below_the_minimum_number_of_returns():
    closes = [100.0 + i for i in range(MIN_VOLATILITY_RETURNS)]  # n-1 returns
    assert annualized_volatility(closes) is None


def test_volatility_of_a_perfectly_flat_series_is_zero_not_none():
    """Flat IS a measurement -- a contract that did not move has a realised
    volatility of zero, which is different from not knowing."""
    assert annualized_volatility([50.0] * 30) == 0.0


def test_volatility_matches_the_annualised_sample_stddev_of_log_returns():
    closes = [100.0, 102.0, 101.0, 104.0, 103.0] * 6  # 30 closes, 29 returns
    result = annualized_volatility(closes)

    window = closes[-(energy_service.VOLATILITY_SESSIONS + 1) :]
    returns = [math.log(b / a) for a, b in zip(window, window[1:], strict=False)]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    expected = round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 1)

    assert result == expected


def test_volatility_reads_only_the_most_recent_window():
    """A calm month after a violent year must read as calm; the window is the
    last ~21 sessions, not the whole series."""
    violent = [100.0, 160.0] * 40
    calm = [100.0] * 40
    assert annualized_volatility(violent + calm) == 0.0


# --- indicators_from_history ----------------------------------------------


def test_empty_history_yields_all_none_and_no_sparkline():
    out = indicators_from_history([])
    assert out.value is None
    assert out.week_change_pct is None
    assert out.month_change_pct is None
    assert out.ytd_change_pct is None
    assert out.percentile_1y is None
    assert out.volatility_30d_pct is None
    assert out.sparkline == []


def test_day_change_compares_the_last_two_closes():
    out = indicators_from_history(series([100.0, 110.0]))
    assert out.value == 110.0
    assert out.day_change_pct == 10.0


def test_a_single_close_supports_no_change_at_all():
    out = indicators_from_history(series([100.0]))
    assert out.value == 100.0
    assert out.day_change_pct is None
    assert out.week_change_pct is None


def test_week_change_is_none_when_the_series_does_not_reach_back_a_week():
    """A three-day series must NOT report its three-day move as a weekly one."""
    out = indicators_from_history(series([100.0, 101.0, 120.0]))
    assert out.week_change_pct is None


def test_week_and_month_changes_use_the_close_at_or_before_the_cutoff():
    closes = [float(100 + i) for i in range(60)]  # 60 daily closes, ending 159
    out = indicators_from_history(series(closes))

    assert out.value == 159.0
    assert out.week_change_pct == pct_change(159.0, 152.0)
    assert out.month_change_pct == pct_change(159.0, 129.0)


def test_ytd_change_is_measured_against_the_previous_years_last_close():
    end = datetime(2026, 3, 2, tzinfo=timezone.utc)
    # 2025-12-30, 2025-12-31, then two 2026 sessions.
    points = [
        (datetime(2025, 12, 30, tzinfo=timezone.utc), 90.0),
        (datetime(2025, 12, 31, tzinfo=timezone.utc), 100.0),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), 105.0),
        (end, 120.0),
    ]
    out = indicators_from_history(points)
    assert out.ytd_change_pct == pct_change(120.0, 100.0)


def test_ytd_change_is_none_when_the_series_starts_inside_this_year():
    """No December close in the window means no year-to-date figure -- never a
    two-week change wearing a YTD label."""
    points = [
        (datetime(2026, 1, 5, tzinfo=timezone.utc), 100.0),
        (datetime(2026, 1, 20, tzinfo=timezone.utc), 110.0),
    ]
    assert indicators_from_history(points).ytd_change_pct is None


def test_percentile_places_the_latest_close_inside_its_own_year():
    out = indicators_from_history(series([10.0, 20.0, 30.0, 40.0]))
    # 40 is at or above all four closes.
    assert out.percentile_1y == 100.0

    out_low = indicators_from_history(series([40.0, 30.0, 20.0, 10.0]))
    assert out_low.percentile_1y == 25.0


# `percentile_of` moved here from cockpit_signals_service with the series it is
# computed over. Its own two tests came with it: `indicators_from_history` never
# reaches it with an empty series (it returns early on one, energy_service.py),
# so nothing else in the suite can see the empty case at all.


def test_percentile_of_places_a_value_inside_its_own_series():
    assert percentile_of(5.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 100.0
    assert percentile_of(3.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 60.0
    assert percentile_of(0.5, [1.0, 2.0]) == 0.0


def test_percentile_of_is_none_for_an_empty_series_never_a_defaulted_fifty():
    """The promise the docstring makes, and the only test that can hold it to it.

    A defaulted 50 would place Brent in the middle of a year nobody measured,
    and the fuel tile bands its level off exactly this number -- "orta seviye"
    printed out of an empty series is an invented reading, not a missing one.
    """
    assert percentile_of(95.0, []) is None


def test_sparkline_thins_a_daily_year_but_plots_only_real_closes():
    closes = [float(i) for i in range(251)]
    out = indicators_from_history(series(closes))

    assert len(out.sparkline) < len(closes)
    assert out.sparkline[-1] == closes[-1]  # ends on the latest close
    assert all(point in closes for point in out.sparkline)  # nothing averaged


# --- the derived jet-fuel row --------------------------------------------


def test_jet_fuel_percentages_are_computed_over_the_derived_series():
    """Adding a constant to a series does NOT preserve its percentage changes,
    so the jet-fuel row must not inherit Brent's."""
    brent = series([80.0, 88.0])
    jet = [
        (ts, round(close + energy_service.JET_FUEL_CRACK_SPREAD_USD, 2)) for ts, close in brent
    ]

    brent_day = indicators_from_history(brent).day_change_pct
    jet_day = indicators_from_history(jet).day_change_pct

    assert brent_day == 10.0
    assert jet_day is not None
    assert jet_day < brent_day  # same absolute move, bigger base, smaller percent
    assert jet_day == pct_change(145.0, 137.0)


# --- the board and its wiring --------------------------------------------


async def test_energy_board_covers_brent_wti_gas_and_the_derived_jet_row(monkeypatch):
    prices = {"BZ=F": 88.0, "CL=F": 85.0, "NG=F": 2.9}

    async def fake_history(base_url, symbol, period):
        assert period == "1y_daily"  # daily closes, or the volatility is noise
        return series([prices[symbol] - 5, prices[symbol] - 2, prices[symbol]])

    monkeypatch.setattr(energy_service, "fetch_history", fake_history)

    rows = await energy_service.energy_metrics()
    by_key = {row.metric_key: row for row in rows}

    assert set(by_key) == {"oil_price", "fuel_price", "wti_price", "natgas_price"}
    assert by_key["natgas_price"].unit == "$/MMBtu"  # never blended into a $/bbl index
    assert by_key["wti_price"].is_estimate is False
    assert by_key["oil_price"].indicators.value == 88.0

    jet = by_key["fuel_price"]
    assert jet.is_estimate is True
    assert jet.note_tr is not None and "crack" in jet.note_tr
    assert jet.indicators.value == round(88.0 + energy_service.JET_FUEL_CRACK_SPREAD_USD, 2)


async def test_energy_board_thins_to_empty_indicators_when_yahoo_is_down(monkeypatch):
    """fetch_history returns [] on any failure. The panel must degrade to "—"
    rather than fail the request or invent a last-known value."""

    async def dead_history(base_url, symbol, period):
        return []

    monkeypatch.setattr(energy_service, "fetch_history", dead_history)

    rows = await energy_service.energy_metrics()

    assert len(rows) == 4
    assert all(row.indicators.value is None for row in rows)
    assert all(row.indicators.percentile_1y is None for row in rows)


def test_every_energy_metric_has_a_detail_page_and_a_history_symbol():
    """Each panel row links to /kpi/<metric_key>, which 404s unless the metric
    is in KPI_DISPLAY -- and would draw a single point unless it also has an
    external history archive."""
    from app.api.v1.kpis import KPI_DISPLAY, YAHOO_HISTORY_SYMBOLS

    for metric_key, _symbol, _unit, _label in energy_service.LIVE_ENERGY_CONTRACTS:
        assert metric_key in KPI_DISPLAY
        assert metric_key in YAHOO_HISTORY_SYMBOLS


def test_every_live_fx_pair_has_a_detail_page_and_a_history_symbol():
    """The compact market strip links every card to its own detail page."""
    from app.api.v1.kpis import KPI_DISPLAY, YAHOO_HISTORY_SYMBOLS
    from app.services.kpi_service import FX_PAIR_LABELS, LIVE_FX_PAIRS

    for metric_key, _symbol, _base, _quote, _unit in LIVE_FX_PAIRS:
        assert metric_key in KPI_DISPLAY
        assert metric_key in YAHOO_HISTORY_SYMBOLS
        assert metric_key in FX_PAIR_LABELS
