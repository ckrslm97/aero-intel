"""Last-year (2025) comparison on the KPI list + the per-metric CSV export.

The LY value comes from the seeded IATA 2025 column for published metrics and
from Yahoo Finance's own archive for market metrics -- and must degrade to
"no LY comparison" (never a 500) when neither is available.
"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import kpis as kpis_api
from app.core.db import get_db
from app.repositories.kpi_repository import KpiRepository

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
LY_DATE = datetime(2025, 12, 31, tzinfo=timezone.utc)


@pytest.fixture
def kpi_app(db_session):
    """The real kpis router mounted at the real prefix, with the DB dependency
    pointed at the test session (same pattern as test_auth.py)."""
    app = FastAPI()
    app.include_router(kpis_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


async def _get(app: FastAPI, path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _kpi(payload: list[dict], metric_key: str) -> dict:
    return next(item for item in payload if item["metric_key"] == metric_key)


# --- LY comparison on GET /api/v1/kpis ---


async def test_seeded_metric_with_2025_observation_gets_ly_fields(kpi_app, db_session):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 80.0, "%", "IATA", True, LY_DATE)
    repo.record("load_factor", 82.0, "%", "IATA", True, datetime(2026, 6, 1, tzinfo=timezone.utc))
    repo.record("load_factor", 84.0, "%", "IATA", True, NOW)
    await db_session.commit()

    response = await _get(kpi_app, "/api/v1/kpis")

    assert response.status_code == 200
    kpi = _kpi(response.json(), "load_factor")
    assert kpi["ly_value"] == 80.0
    assert kpi["ly_delta_pct"] == round((84.0 - 80.0) / 80.0 * 100, 2)  # 5.0
    assert kpi["comparison_label"] == "2025'e göre"
    # Existing delta_pct semantics are untouched: vs the previous observation.
    assert kpi["delta_pct"] == round((84.0 - 82.0) / 82.0 * 100, 2)


async def test_metric_without_2025_observation_or_yahoo_mapping_has_no_ly(kpi_app, db_session):
    repo = KpiRepository(db_session)
    repo.record("flights_airborne", 12000, "uçuş", "OpenSky", False, NOW)
    await db_session.commit()

    response = await _get(kpi_app, "/api/v1/kpis")

    assert response.status_code == 200
    kpi = _kpi(response.json(), "flights_airborne")
    assert kpi["ly_value"] is None
    assert kpi["ly_delta_pct"] is None
    assert kpi["comparison_label"] == "önceki ölçüme göre"


async def test_market_metric_reads_ly_from_the_stored_row_not_yahoo(
    kpi_app, db_session, monkeypatch
):
    """The list endpoint must not touch Yahoo: two live history calls with a
    15s timeout each were most of why /kpis measured ~10s in production. The
    refresh job stores the price a year ago under "<metric>_ly" instead."""
    repo = KpiRepository(db_session)
    repo.record("oil_price", 80.0, "$/bbl", "Yahoo Finance (BZ=F)", False, NOW)
    repo.record(
        "oil_price_ly", 64.0, "$/bbl", "Yahoo Finance (BZ=F, 1 yıl önce)", False, NOW,
        is_primary=False,
    )
    await db_session.commit()

    calls: list[tuple[str, str]] = []

    async def spy_fetch_history(base_url, symbol, period):
        calls.append((symbol, period))
        return [(datetime(2025, 7, 18, tzinfo=timezone.utc), 1.0)]

    monkeypatch.setattr(kpis_api, "fetch_history", spy_fetch_history)

    response = await _get(kpi_app, "/api/v1/kpis")

    assert response.status_code == 200
    kpi = _kpi(response.json(), "oil_price")
    assert kpi["ly_value"] == 64.0
    assert kpi["ly_delta_pct"] == round((80.0 - 64.0) / 64.0 * 100, 2)  # 25.0
    assert kpi["comparison_label"] == "2025'e göre"
    assert calls == []  # no network on the request path


async def test_market_metric_without_a_stored_ly_row_degrades_honestly(
    kpi_app, db_session, monkeypatch
):
    repo = KpiRepository(db_session)
    repo.record("oil_price", 80.0, "$/bbl", "Yahoo Finance (BZ=F)", False, NOW)
    await db_session.commit()

    async def unexpected_history(base_url, symbol, period):
        raise AssertionError("the list endpoint must not call Yahoo")

    monkeypatch.setattr(kpis_api, "fetch_history", unexpected_history)

    response = await _get(kpi_app, "/api/v1/kpis")

    assert response.status_code == 200
    kpi = _kpi(response.json(), "oil_price")
    assert kpi["ly_value"] is None
    assert kpi["ly_delta_pct"] is None
    assert kpi["comparison_label"] == "önceki ölçüme göre"


# --- GET /api/v1/kpis/{metric_key}/observations.csv ---


async def test_csv_export_returns_full_history_ascending(kpi_app, db_session):
    repo = KpiRepository(db_session)
    # Recorded newest-first to prove the export sorts ascending itself.
    repo.record(
        "load_factor", 84.0, "%", "IATA", True, NOW, source_url="https://iata.org/outlook"
    )
    repo.record("load_factor", 80.0, "%", "IATA", True, LY_DATE)
    await db_session.commit()

    response = await _get(kpi_app, "/api/v1/kpis/load_factor/observations.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="aerointel-kpi-load_factor.csv"'
    )
    lines = response.text.splitlines()
    assert lines[0] == "date,value,unit,source,source_url"
    assert lines[1] == "2025-12-31,80.0,%,IATA,"
    assert lines[2] == "2026-07-18,84.0,%,IATA,https://iata.org/outlook"
    assert len(lines) == 3


async def test_csv_export_unknown_metric_is_404(kpi_app):
    response = await _get(kpi_app, "/api/v1/kpis/no_such_metric/observations.csv")

    assert response.status_code == 404
