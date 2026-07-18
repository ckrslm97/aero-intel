"""Endpoint behaviour for /funds -- called directly as route functions with the
test session (admin_status test pattern). Empty-database honesty matters here:
cards render with null values and explicit statuses, never fabricated numbers.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.funds import (
    get_fund_detail,
    get_fund_history,
    get_fund_holdings,
    get_portfolios,
    list_funds,
)
from app.funds_catalog import FUND_CATALOG, get_fund_spec
from app.models.fund import OFFICIAL_SINGLE_SOURCE, VERIFIED, FundHolding
from app.repositories.fund_repository import FundRepository
from app.schemas.fund import DISCLAIMER_TR

NOW = datetime.now(timezone.utc).replace(microsecond=0)


async def test_list_funds_bootstraps_catalog_on_empty_db(db_session):
    funds = await list_funds(db_session)

    assert len(funds) == len(FUND_CATALOG)
    by_symbol = {f.symbol: f for f in funds}
    assert by_symbol["XLV"].target_weight == 0.40
    # No data yet -> honest nulls, not invented numbers.
    assert by_symbol["XLV"].value is None
    assert by_symbol["XLV"].verification_status is None
    assert by_symbol["AFS"].metadata_verified is False


async def test_list_funds_returns_latest_value_and_trend(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    for i, value in enumerate([100.0, 101.0, 103.0]):
        repo.record_price(fund.id, value, NOW - timedelta(days=3 - i), "Yahoo Finance", VERIFIED)
    await db_session.commit()

    funds = await list_funds(db_session)
    xlv = next(f for f in funds if f.symbol == "XLV")

    assert xlv.value == 103.0
    assert xlv.trend == [100.0, 101.0, 103.0]
    assert xlv.delta_pct == round((103.0 - 101.0) / 101.0 * 100, 2)
    assert xlv.verification_status == VERIFIED


async def test_fund_detail_unknown_symbol_404(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_fund_detail("NOPE", db_session)
    assert exc.value.status_code == 404


async def test_fund_detail_includes_analysis_and_disclaimer(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("AFS"))
    repo.record_price(fund.id, 1.234, NOW, "TEFAS", OFFICIAL_SINGLE_SOURCE)
    await repo.upsert_analysis(
        "fund", fund.id, date(2026, 7, 18), "Analiz metni.", "neutral", "heuristic", "fp"
    )
    await db_session.commit()

    detail = await get_fund_detail("afs", db_session)  # case-insensitive lookup

    assert detail.value == 1.234
    assert detail.verification_status == OFFICIAL_SINGLE_SOURCE
    assert detail.analysis.body_tr == "Analiz metni."
    assert detail.analysis.provider == "heuristic"
    assert detail.disclaimer == DISCLAIMER_TR
    assert detail.analysis.disclaimer == DISCLAIMER_TR


async def test_fund_history_periods_filter(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    repo.record_price(fund.id, 90.0, NOW - timedelta(days=200), "Yahoo Finance", VERIFIED)
    repo.record_price(fund.id, 100.0, NOW - timedelta(days=10), "Yahoo Finance", VERIFIED)
    await db_session.commit()

    month = await get_fund_history("XLV", "1m", db_session)
    year = await get_fund_history("XLV", "1y", db_session)

    assert [p.value for p in month.points] == [100.0]
    assert [p.value for p in year.points] == [90.0, 100.0]
    assert year.currency == "USD"


async def test_fund_holdings_payload(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("ARKG"))
    as_of = date(2026, 7, 15)
    db_session.add_all(
        [
            FundHolding(
                fund_id=fund.id, as_of=as_of, rank=1, ticker="CRSP",
                holding_name="CRISPR Therapeutics", weight_pct=9.5,
                source="ark_funds", verification_status=VERIFIED,
            ),
            FundHolding(
                fund_id=fund.id, as_of=as_of, rank=2, ticker="TXG",
                holding_name="10x Genomics", weight_pct=7.1,
                source="ark_funds", verification_status=VERIFIED,
            ),
        ]
    )
    await db_session.commit()

    payload = await get_fund_holdings("ARKG", db_session)

    assert payload.as_of == as_of
    assert payload.source == "ark_funds"
    assert payload.is_top10_only is False
    assert [h.ticker for h in payload.holdings] == ["CRSP", "TXG"]


async def test_portfolio_view_weights_and_disclaimer(db_session):
    payload = await get_portfolios(db_session)

    assert payload.disclaimer == DISCLAIMER_TR
    us_weights = {f.symbol: f.target_weight for f in payload.us.funds}
    assert us_weights == {"XLV": 0.40, "VHT": 0.20, "XLF": 0.20, "XBI": 0.10, "ARKG": 0.10}
    tr_weights = {f.symbol: f.target_weight for f in payload.tr.funds}
    assert tr_weights == {"AFS": 0.35, "TBE": 0.25, "TI2": 0.20, "MAC": 0.20}
    # No data yet -> the weighted figure must be None, never a partial sum.
    assert payload.us.weighted_return_1y_pct is None
