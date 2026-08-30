"""The jet-fuel detail page's history must use the same derivation as its value.

Regression: `_load_history` kept applying an old 1.18x rule of thumb to Brent's
closes long after kpi_service.py moved the live jet-fuel value onto IATA's
published additive crack spread. The page therefore drew a history ending ~40%
below the number printed above it -- a visible cliff between the last plotted
point and today's reading, with no honest reading of the chart available.

These tests pin the two halves together: the history is Brent + the spread, and
the last historical point lines up with what refresh_all_kpis would record for
the same Brent price.
"""
from datetime import datetime, timezone

from app.api.v1 import kpis
from app.services.kpi_service import JET_FUEL_CRACK_SPREAD_USD

BRENT_CLOSES = (
    (datetime(2026, 7, 1, tzinfo=timezone.utc), 90.0),
    (datetime(2026, 7, 2, tzinfo=timezone.utc), 95.0),
)


def _stub_history(monkeypatch):
    async def fake_history(base_url, symbol, period):
        assert symbol == "BZ=F", "jet fuel history must be built from Brent's own closes"
        return list(BRENT_CLOSES)

    monkeypatch.setattr(kpis, "fetch_history", fake_history)


async def test_fuel_history_adds_the_crack_spread_rather_than_multiplying(
    db_session, monkeypatch
):
    _stub_history(monkeypatch)

    history, is_external = await kpis._load_history(db_session, "fuel_price", "1m")

    assert is_external is True
    assert [point.value for point in history] == [
        round(90.0 + JET_FUEL_CRACK_SPREAD_USD, 2),
        round(95.0 + JET_FUEL_CRACK_SPREAD_USD, 2),
    ]
    # The old bug, stated as the thing that must not come back.
    assert history[-1].value != round(95.0 * 1.18, 2)


async def test_fuel_history_ends_where_the_recorded_value_would_start(
    db_session, monkeypatch
):
    """Last plotted point == what kpi_service would record for that Brent."""
    _stub_history(monkeypatch)

    history, _ = await kpis._load_history(db_session, "fuel_price", "1m")
    latest_brent = BRENT_CLOSES[-1][1]

    assert history[-1].value == round(latest_brent + JET_FUEL_CRACK_SPREAD_USD, 2)


async def test_oil_history_is_left_untouched_by_the_fuel_derivation(
    db_session, monkeypatch
):
    _stub_history(monkeypatch)

    history, _ = await kpis._load_history(db_session, "oil_price", "1m")

    assert [point.value for point in history] == [90.0, 95.0]
