from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.kpi import KPI
from app.repositories.kpi_repository import KpiRepository
from app.services import kpi_service

# Last-year market prices are fetched by the refresh job (never on the request
# path), so every test that runs a refresh has to stub the history call too --
# otherwise the suite quietly reaches out to Yahoo.
LY_HISTORY = {"BZ=F": 64.0, "TRY=X": 34.0}


async def fake_history(base_url, symbol, period):
    return [
        (datetime(2025, 7, 18, tzinfo=timezone.utc), LY_HISTORY[symbol]),
        (datetime(2026, 7, 17, tzinfo=timezone.utc), LY_HISTORY[symbol] + 10),
    ]


# Every symbol the refresh job asks for a live quote, derived from the service's
# own tables rather than transcribed. Five copies of a hand-written dict used to
# live in this file, and adding a currency pair meant editing all five -- which
# is exactly what broke when EUR/TRY and GBP/USD were added.
QUOTES: dict[str, float] = {
    "BZ=F": 80.0,
    **{symbol: 70.0 for _, symbol, _, _ in kpi_service.LIVE_ENERGY_CONTRACTS},
    **{
        symbol: rate
        for (_, symbol, _, _, _), rate in zip(
            kpi_service.LIVE_FX_PAIRS,
            (40.0, 43.0, 1.08, 1.35, 149.0, 0.84, 7.2),
            strict=True,
        )
    },
}

# What one full refresh writes, stated as its parts so a new pair or contract
# moves these counts on its own.
_AIRBORNE_ROWS = 2  # flights_airborne + the derived flights_today
_BRENT_ROWS = 2  # oil_price + the derived fuel_price
_ENERGY_ROWS = len(kpi_service.LIVE_ENERGY_CONTRACTS)
_FX_PRIMARY_ROWS = len(kpi_service.LIVE_FX_PAIRS)
_FX_CROSSCHECK_ROWS = len(kpi_service.LIVE_FX_PAIRS)
_LY_ROWS = 2  # oil_price_ly + fx_usd_try_ly

LIVE_ROWS = (
    _AIRBORNE_ROWS
    + _BRENT_ROWS
    + _ENERGY_ROWS
    + _FX_PRIMARY_ROWS
    + _FX_CROSSCHECK_ROWS
    + _LY_ROWS
)


async def fake_airborne(base_url):
    return 100


async def fake_quote(base_url, symbol):
    return QUOTES[symbol]


async def fake_frankfurter(base_currency, quote_currency):
    return 40.2


def _stub_feeds(monkeypatch, *, history=fake_history, frankfurter=fake_frankfurter):
    monkeypatch.setattr(kpi_service, "fetch_airborne_count", fake_airborne)
    monkeypatch.setattr(kpi_service, "fetch_quote", fake_quote)
    monkeypatch.setattr(kpi_service, "fetch_history", history)
    monkeypatch.setattr(kpi_service, "fetch_frankfurter_rate", frankfurter)


async def test_refresh_all_kpis_records_real_and_estimated_metrics(db_session, monkeypatch):
    _stub_feeds(monkeypatch)

    recorded = await kpi_service.refresh_all_kpis(db_session)

    # Every live row, plus one row per published IATA figure, which an empty
    # database has none of yet.
    assert recorded == LIVE_ROWS + len(kpi_service.latest_published_estimates())

    result = await db_session.execute(select(KPI).where(KPI.metric_key == "flights_airborne"))
    airborne = result.scalar_one()
    assert airborne.value == 100
    assert airborne.is_estimate is False
    assert airborne.is_primary is True

    result = await db_session.execute(select(KPI).where(KPI.metric_key == "fuel_price"))
    fuel = result.scalar_one()
    # Jet fuel = Brent + IATA's published crack spread, not a multiplier.
    assert fuel.value == round(80.0 + kpi_service.JET_FUEL_CRACK_SPREAD_USD, 2)
    assert fuel.is_estimate is True

    result = await db_session.execute(
        select(KPI).where(KPI.metric_key == "fx_usd_try").order_by(KPI.is_primary.desc())
    )
    fx_rows = result.scalars().all()
    assert len(fx_rows) == 2
    primary, secondary = fx_rows
    assert primary.value == 40.0
    assert primary.is_primary is True
    assert secondary.value == 40.2
    assert secondary.is_primary is False
    assert secondary.source == "Frankfurter.app (ECB referans kurları)"

    published = kpi_service.latest_published_estimates()
    result = await db_session.execute(select(KPI).where(KPI.metric_key == "total_aviation_revenue_ytd"))
    total_revenue = result.scalar_one()
    assert total_revenue.value == (
        published["passenger_revenue_ytd"][0] + published["ancillary_revenue_ytd"][0]
    )


async def test_refresh_records_the_new_energy_contracts_as_their_own_metrics(
    db_session, monkeypatch
):
    """WTI and Henry Hub gas are traded contracts in their own right, not
    something derived from Brent -- each gets its own primary row, its own
    unit, and is marked as a real reading rather than an estimate."""
    _stub_feeds(monkeypatch)

    await kpi_service.refresh_all_kpis(db_session)

    for metric_key, symbol, unit, _label in kpi_service.LIVE_ENERGY_CONTRACTS:
        row = (
            await db_session.execute(select(KPI).where(KPI.metric_key == metric_key))
        ).scalar_one()
        assert row.value == QUOTES[symbol]
        assert row.unit == unit
        assert row.is_estimate is False
        assert row.is_primary is True
        assert symbol in row.source


async def test_refresh_records_every_live_fx_pair_including_the_new_ones(db_session, monkeypatch):
    """EUR/TRY and GBP/USD were added to the board by the Kokpit revision; a
    pair declared in LIVE_FX_PAIRS but never written would show as a
    permanently empty card."""
    _stub_feeds(monkeypatch)

    await kpi_service.refresh_all_kpis(db_session)

    for metric_key, symbol, _base, _quote, unit in kpi_service.LIVE_FX_PAIRS:
        row = (
            await db_session.execute(
                select(KPI).where(KPI.metric_key == metric_key, KPI.is_primary.is_(True))
            )
        ).scalar_one()
        assert row.value == QUOTES[symbol]
        assert row.unit == unit

    assert "fx_eur_try" in kpi_service.FX_PAIR_LABELS
    assert kpi_service.FX_PAIR_LABELS["fx_eur_try"] == "EUR/TRY"
    assert kpi_service.FX_PAIR_LABELS["fx_gbp_usd"] == "GBP/USD"


async def test_refresh_does_not_rewrite_published_figures_that_have_not_moved(db_session, monkeypatch):
    """The second run of the day must add live readings only.

    Re-recording an unchanged IATA figure every 15 minutes is what previously
    turned one number into ~100 identical rows and flattened the trend line.
    """
    _stub_feeds(monkeypatch)

    await kpi_service.refresh_all_kpis(db_session)
    second_run = await kpi_service.refresh_all_kpis(db_session)

    assert second_run == LIVE_ROWS  # the live rows, and nothing else


async def test_refresh_all_kpis_skips_frankfurter_row_when_unavailable(db_session, monkeypatch):
    async def fake_frankfurter_unavailable(base_currency, quote_currency):
        return None

    _stub_feeds(monkeypatch, frankfurter=fake_frankfurter_unavailable)

    recorded = await kpi_service.refresh_all_kpis(db_session)

    # One fewer row per pair -- no cross-check row for any of them.
    assert recorded == (
        LIVE_ROWS - _FX_CROSSCHECK_ROWS + len(kpi_service.latest_published_estimates())
    )

    result = await db_session.execute(select(KPI).where(KPI.metric_key == "fx_usd_try"))
    fx_rows = result.scalars().all()
    assert len(fx_rows) == 1


async def test_kpi_repository_trend_excludes_secondary_sources(db_session):
    repo = KpiRepository(db_session)

    base = datetime.now(timezone.utc)
    for i, value in enumerate([10.0, 20.0, 30.0]):
        repo.record("test_metric", value, "unit", "test", False, base + timedelta(minutes=i))
    repo.record("test_metric", 999.0, "unit", "corroborator", False, base, is_primary=False)
    await db_session.commit()

    trend = await repo.trend("test_metric", points=12)

    assert [t.value for t in trend] == [10.0, 20.0, 30.0]


async def test_kpi_repository_latest_corroborations_dedupes_by_source(db_session):
    repo = KpiRepository(db_session)

    base = datetime.now(timezone.utc)
    repo.record("fx_usd_try", 40.0, "TRY", "Yahoo Finance", False, base, is_primary=True)
    repo.record("fx_usd_try", 40.1, "TRY", "Frankfurter.app", False, base, is_primary=False)
    repo.record(
        "fx_usd_try", 40.2, "TRY", "Frankfurter.app", False, base + timedelta(minutes=1), is_primary=False
    )
    await db_session.commit()

    corroborations = await repo.latest_corroborations("fx_usd_try")

    assert len(corroborations) == 1
    assert corroborations[0].value == 40.2  # the more recent of the two Frankfurter rows


async def test_refresh_stores_last_year_market_prices_off_the_request_path(db_session, monkeypatch):
    """The dashboard must never call Yahoo while serving a request, so the
    refresh job stores each market metric's price a year ago under a
    "<metric>_ly" key, outside the live series that feeds the sparkline."""
    _stub_feeds(monkeypatch)

    await kpi_service.refresh_all_kpis(db_session)

    row = (
        await db_session.execute(select(KPI).where(KPI.metric_key == "oil_price_ly"))
    ).scalar_one()
    assert row.value == 64.0  # the FIRST point of the trailing-1y series
    assert row.is_primary is False  # must not feed the live trend

    # The live series is untouched by the LY bookkeeping.
    trend = await KpiRepository(db_session).trend("oil_price")
    assert [p.value for p in trend] == [80.0]


async def test_refresh_survives_a_yahoo_history_outage(db_session, monkeypatch):
    async def broken_history(base_url, symbol, period):
        raise RuntimeError("yahoo down")

    _stub_feeds(monkeypatch, history=broken_history)

    # The live readings still land; only the LY rows are missing.
    recorded = await kpi_service.refresh_all_kpis(db_session)
    assert recorded == LIVE_ROWS - _LY_ROWS + len(kpi_service.latest_published_estimates())
    assert (
        await db_session.execute(select(KPI).where(KPI.metric_key == "oil_price_ly"))
    ).scalar_one_or_none() is None
