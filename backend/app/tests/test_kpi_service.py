from app.models.kpi import KPI
from app.repositories.kpi_repository import KpiRepository
from app.services import kpi_service


async def test_refresh_all_kpis_records_real_and_estimated_metrics(db_session, monkeypatch):
    async def fake_airborne(base_url):
        return 100

    async def fake_quote(base_url, symbol):
        return {"BZ=F": 80.0, "TRY=X": 40.0}[symbol]

    monkeypatch.setattr(kpi_service, "fetch_airborne_count", fake_airborne)
    monkeypatch.setattr(kpi_service, "fetch_quote", fake_quote)

    recorded = await kpi_service.refresh_all_kpis(db_session)

    assert recorded == 8

    from sqlalchemy import select

    result = await db_session.execute(select(KPI).where(KPI.metric_key == "flights_airborne"))
    airborne = result.scalar_one()
    assert airborne.value == 100
    assert airborne.is_estimate is False

    result = await db_session.execute(select(KPI).where(KPI.metric_key == "fuel_price"))
    fuel = result.scalar_one()
    assert fuel.value == round(80.0 * 1.18, 2)
    assert fuel.is_estimate is True


async def test_kpi_repository_trend_orders_oldest_first(db_session):
    repo = KpiRepository(db_session)
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc)
    for i, value in enumerate([10.0, 20.0, 30.0]):
        repo.record("test_metric", value, "unit", "test", False, base + timedelta(minutes=i))
    await db_session.commit()

    trend = await repo.trend("test_metric", points=12)

    assert [t.value for t in trend] == [10.0, 20.0, 30.0]
