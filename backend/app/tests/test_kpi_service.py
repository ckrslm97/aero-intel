from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.kpi import KPI
from app.repositories.kpi_repository import KpiRepository
from app.services import kpi_service


async def test_refresh_all_kpis_records_real_and_estimated_metrics(db_session, monkeypatch):
    async def fake_airborne(base_url):
        return 100

    async def fake_quote(base_url, symbol):
        return {"BZ=F": 80.0, "TRY=X": 40.0}[symbol]

    async def fake_frankfurter(base_currency, quote_currency):
        return 40.2

    monkeypatch.setattr(kpi_service, "fetch_airborne_count", fake_airborne)
    monkeypatch.setattr(kpi_service, "fetch_quote", fake_quote)
    monkeypatch.setattr(kpi_service, "fetch_frankfurter_rate", fake_frankfurter)

    recorded = await kpi_service.refresh_all_kpis(db_session)

    # 6 live rows -- flights_airborne, flights_today, oil_price, fuel_price,
    # fx_usd_try (primary) and its Frankfurter cross-check -- plus one row per
    # published IATA figure, which an empty database has none of yet.
    assert recorded == 6 + len(kpi_service.latest_published_estimates())

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


async def test_refresh_does_not_rewrite_published_figures_that_have_not_moved(db_session, monkeypatch):
    """The second run of the day must add live readings only.

    Re-recording an unchanged IATA figure every 15 minutes is what previously
    turned one number into ~100 identical rows and flattened the trend line.
    """
    async def fake_airborne(base_url):
        return 100

    async def fake_quote(base_url, symbol):
        return {"BZ=F": 80.0, "TRY=X": 40.0}[symbol]

    async def fake_frankfurter(base_currency, quote_currency):
        return 40.2

    monkeypatch.setattr(kpi_service, "fetch_airborne_count", fake_airborne)
    monkeypatch.setattr(kpi_service, "fetch_quote", fake_quote)
    monkeypatch.setattr(kpi_service, "fetch_frankfurter_rate", fake_frankfurter)

    await kpi_service.refresh_all_kpis(db_session)
    second_run = await kpi_service.refresh_all_kpis(db_session)

    assert second_run == 6  # the live rows, and nothing else


async def test_refresh_all_kpis_skips_frankfurter_row_when_unavailable(db_session, monkeypatch):
    async def fake_airborne(base_url):
        return 100

    async def fake_quote(base_url, symbol):
        return {"BZ=F": 80.0, "TRY=X": 40.0}[symbol]

    async def fake_frankfurter_unavailable(base_currency, quote_currency):
        return None

    monkeypatch.setattr(kpi_service, "fetch_airborne_count", fake_airborne)
    monkeypatch.setattr(kpi_service, "fetch_quote", fake_quote)
    monkeypatch.setattr(kpi_service, "fetch_frankfurter_rate", fake_frankfurter_unavailable)

    recorded = await kpi_service.refresh_all_kpis(db_session)

    # one fewer than a full run -- no cross-check row
    assert recorded == 5 + len(kpi_service.latest_published_estimates())

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
