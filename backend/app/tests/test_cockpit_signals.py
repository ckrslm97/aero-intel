"""Kokpit "Sinyal Panosu" thresholds, band by band.

The tiles exist so a reader can see the rule that produced a level. These tests
exist so the rule cannot move without someone saying so: every boundary below
is asserted from BOTH sides, and the tables themselves are checked for the
open-ended final band `band_for` relies on.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Response

from app.api.v1 import kokpit
from app.repositories.kpi_repository import KpiRepository
from app.services import cockpit_signals_service as svc


# --- The tables themselves ------------------------------------------------

ALL_TABLES = (
    svc.FX_30D_ABS_MOVE_BANDS,
    svc.FUEL_PERCENTILE_BANDS,
    svc.FUEL_30D_RISE_BANDS,
    svc.RISK_HIGH_COUNT_BANDS,
    svc.COMPETITOR_48H_COUNT_BANDS,
)


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_threshold_table_ends_open_ended(table):
    """band_for() falls off the end of a table whose last row has an upper
    bound -- so no table may have one."""
    assert table[-1].upper is None
    assert all(band.upper is not None for band in table[:-1])


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_threshold_table_is_written_low_to_high(table):
    uppers = [band.upper for band in table[:-1]]
    assert uppers == sorted(uppers)


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_band_names_a_known_level(table):
    assert all(band.level in svc.LEVEL_LABELS_TR for band in table)


def test_band_for_rejects_a_table_with_no_open_final_band():
    with pytest.raises(ValueError):
        svc.band_for(99.0, (svc.Band(1.0, svc.GOOD),))


def test_worst_picks_the_most_severe_level():
    assert svc.worst(svc.GOOD, svc.CRITICAL, svc.WARNING) == svc.CRITICAL
    assert svc.worst(svc.GOOD, svc.GOOD) == svc.GOOD


# --- Kur Riski ------------------------------------------------------------


@pytest.mark.parametrize(
    "move_pct,expected",
    [
        (0.0, svc.GOOD),
        (1.99, svc.GOOD),
        (2.0, svc.WARNING),  # boundary: 2% is already "dikkat"
        (4.99, svc.WARNING),
        (5.0, svc.CRITICAL),
        (12.4, svc.CRITICAL),
        # Direction must not matter: a pair moving is neither good nor bad.
        (-1.99, svc.GOOD),
        (-2.0, svc.WARNING),
        (-5.0, svc.CRITICAL),
    ],
)
def test_fx_level_bands_the_absolute_30_day_move(move_pct, expected):
    signal = svc.build_fx_signal(spot=41.7, move_30d_pct=move_pct, forecast_values=[])
    assert signal.level == expected


def test_fx_signal_is_unknown_rather_than_good_without_enough_history():
    signal = svc.build_fx_signal(spot=41.7, move_30d_pct=None, forecast_values=[])
    assert signal.level == svc.UNKNOWN
    assert signal.level_label_tr == "Veri yok"
    assert signal.value_label == "—"


def test_fx_signal_states_the_forecast_range_and_never_an_average():
    signal = svc.build_fx_signal(
        spot=41.70, move_30d_pct=1.0, forecast_values=[51.4, 52.0, 52.0, 66.0]
    )
    # Both ends of the curated range, each a real institution's own number.
    assert "51,40" in signal.reason_tr
    assert "66,00" in signal.reason_tr
    # The mean of those four is 55.35 -- averaging curated forecasts is
    # forbidden by app/ingest/curated_seed.py and must never appear here.
    assert "55,35" not in signal.reason_tr
    assert "ortalama" not in signal.reason_tr.lower()


def test_fx_signal_omits_the_range_when_nothing_is_curated_yet():
    signal = svc.build_fx_signal(spot=41.70, move_30d_pct=1.0, forecast_values=[])
    assert "aralığında" not in signal.reason_tr


# --- Yakıt Riski ----------------------------------------------------------


@pytest.mark.parametrize(
    "percentile,expected",
    [(0.0, svc.GOOD), (49.9, svc.GOOD), (50.0, svc.WARNING), (79.9, svc.WARNING), (80.0, svc.CRITICAL), (100.0, svc.CRITICAL)],
)
def test_fuel_level_bands_the_one_year_percentile(percentile, expected):
    signal = svc.build_fuel_signal(brent=95.0, percentile=percentile, move_30d_pct=0.0)
    assert signal.level == expected


@pytest.mark.parametrize(
    "move_pct,expected",
    [
        (-30.0, svc.GOOD),  # a fall in the cost base is not a cost risk
        (1.99, svc.GOOD),
        (2.0, svc.WARNING),
        (7.99, svc.WARNING),
        (8.0, svc.CRITICAL),
    ],
)
def test_fuel_level_bands_only_rises(move_pct, expected):
    signal = svc.build_fuel_signal(brent=95.0, percentile=10.0, move_30d_pct=move_pct)
    assert signal.level == expected


def test_fuel_level_takes_the_worse_of_the_two_bands():
    # Cheap by percentile, but spiking: the spike wins.
    assert (
        svc.build_fuel_signal(brent=95.0, percentile=5.0, move_30d_pct=12.0).level
        == svc.CRITICAL
    )
    # Expensive but flat: the level wins.
    assert (
        svc.build_fuel_signal(brent=95.0, percentile=95.0, move_30d_pct=0.0).level
        == svc.CRITICAL
    )


def test_fuel_signal_survives_a_yahoo_outage_with_the_delta_alone():
    signal = svc.build_fuel_signal(brent=95.0, percentile=None, move_30d_pct=9.0)
    assert signal.level == svc.CRITICAL
    assert "dilim" not in signal.reason_tr  # no percentile claimed


def test_fuel_signal_is_unknown_when_neither_driver_can_be_read():
    signal = svc.build_fuel_signal(brent=95.0, percentile=None, move_30d_pct=None)
    assert signal.level == svc.UNKNOWN


def test_fuel_signal_says_out_loud_that_it_is_not_a_company_cost():
    signal = svc.build_fuel_signal(brent=95.0, percentile=40.0, move_30d_pct=1.0)
    assert "şirket yakıt maliyeti değil" in signal.reason_tr


def test_fuel_signal_leaves_the_derived_jet_price_to_the_panels_that_show_it():
    """The tile bands Brent, and stops there.

    The jet-fuel number belongs to the market strip and the "Yakıt & Enerji"
    panel, both of which print its derivation right beside it. A third copy in
    this sentence made the tile twice the height of its three neighbours for a
    number the reader had already met twice.
    """
    signal = svc.build_fuel_signal(brent=95.0, percentile=40.0, move_30d_pct=1.0)
    assert "Jet" not in signal.reason_tr
    assert "crack" not in signal.reason_tr


# --- Risk Radarı ----------------------------------------------------------


@pytest.mark.parametrize(
    "high_count,expected",
    [(0, svc.GOOD), (1, svc.WARNING), (2, svc.WARNING), (3, svc.CRITICAL), (11, svc.CRITICAL)],
)
def test_risk_level_bands_the_high_severity_count(high_count, expected):
    signal = svc.build_risk_signal(high_count=high_count, total=high_count + 4)
    assert signal.level == expected


def test_risk_signal_names_the_worst_country_when_there_is_one():
    signal = svc.build_risk_signal(
        high_count=4, total=12, top_country="İtalya", top_country_high=3
    )
    assert "İtalya" in signal.reason_tr
    assert signal.href == "/risk-radari"


def test_risk_signal_omits_the_country_clause_when_nothing_resolved():
    signal = svc.build_risk_signal(high_count=0, total=0)
    assert "En yoğun ülke" not in signal.reason_tr


# --- Rakip Aktivitesi -----------------------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [(0, svc.GOOD), (2, svc.GOOD), (3, svc.WARNING), (5, svc.WARNING), (6, svc.CRITICAL)],
)
def test_competitor_level_bands_the_48h_campaign_count(count, expected):
    signal = svc.build_competitor_signal(
        new_count=count, airline_codes=[], window_hours=48
    )
    assert signal.level == expected


def test_competitor_signal_refuses_to_imply_capacity_or_share():
    signal = svc.build_competitor_signal(
        new_count=7, airline_codes=["EK", "QR"], window_hours=48
    )
    assert "HABER/KAMPANYA" in signal.method_tr
    assert "kapasite" in signal.method_tr
    for forbidden in ("pazar payı verisi", "doluluk"):
        # present only inside the explicit disclaimer, never as a claim
        assert forbidden in signal.method_tr


def test_competitor_signal_adds_the_top_mover_only_when_it_actually_moved():
    moved = svc.build_competitor_signal(
        new_count=1, airline_codes=[], window_hours=48,
        top_mover_name="Emirates", top_mover_delta=6,
    )
    assert "Emirates" in moved.reason_tr

    flat = svc.build_competitor_signal(
        new_count=1, airline_codes=[], window_hours=48,
        top_mover_name="Emirates", top_mover_delta=0,
    )
    assert "Emirates" not in flat.reason_tr


# --- Helpers --------------------------------------------------------------


def test_percentile_of_places_a_value_inside_its_own_series():
    assert svc.percentile_of(5.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 100.0
    assert svc.percentile_of(3.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 60.0
    assert svc.percentile_of(0.5, [1.0, 2.0]) == 0.0


def test_percentile_of_is_none_for_an_empty_series_never_a_defaulted_fifty():
    assert svc.percentile_of(95.0, []) is None


def test_turkish_number_formatting_uses_turkish_separators():
    assert svc.tr_number(1234.5, 2) == "1.234,50"
    assert svc.tr_number(41.7231, 2) == "41,72"
    assert svc.tr_signed_percent(2.36) == "+%2,4"
    assert svc.tr_signed_percent(-2.36) == "-%2,4"
    assert svc.tr_signed_percent(0.0) == "%0,0"


# --- End to end through the endpoint -------------------------------------


async def test_signals_endpoint_returns_all_four_tiles_on_an_empty_database(db_session):
    out = await kokpit.get_cockpit_signals(Response(), db_session)
    assert [signal.key for signal in out.signals] == ["fx", "fuel", "risk", "competitor"]
    # Nothing recorded: the market tiles must say so rather than read green.
    by_key = {signal.key: signal for signal in out.signals}
    assert by_key["fx"].level == svc.UNKNOWN
    assert by_key["fuel"].level == svc.UNKNOWN
    # The counted tiles are genuinely at zero, which IS calm.
    assert by_key["risk"].level == svc.GOOD
    assert by_key["competitor"].level == svc.GOOD


async def test_signals_endpoint_bands_a_real_usd_try_move(db_session, monkeypatch):
    # No Yahoo call on the request path in tests: the fuel percentile degrades
    # to "30-day move only", which is the outage path build_fuel_signal covers.
    async def _no_history(*_args, **_kwargs):
        return []

    monkeypatch.setattr(svc, "fetch_history", _no_history)

    repo = KpiRepository(db_session)
    now = datetime.now(timezone.utc)
    repo.record("fx_usd_try", 40.0, "TRY", "Yahoo Finance (TRY=X)", False, now - timedelta(days=31))
    repo.record("fx_usd_try", 44.0, "TRY", "Yahoo Finance (TRY=X)", False, now)
    await db_session.commit()

    out = await kokpit.get_cockpit_signals(Response(), db_session)
    fx = next(signal for signal in out.signals if signal.key == "fx")
    assert fx.level == svc.CRITICAL  # +10% over 30 days
    assert fx.value_label == "+%10,0"
    assert "44,00" in fx.reason_tr
