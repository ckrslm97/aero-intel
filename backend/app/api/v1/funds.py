"""The /invest module's API: fund list, detail, history, holdings, portfolio
view, and an admin refresh trigger. History is served from our stored
fund_prices (TEFAS can't be re-fetched per request anyway); every payload
carries verification status and the fixed disclaimer.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.logging import get_logger
from app.funds_catalog import MARKET_TR, MARKET_US, get_fund_spec, specs_for_market
from app.models.fund import Fund
from app.repositories.fund_repository import FundRepository
from app.schemas.fund import (
    DISCLAIMER_TR,
    FundAllocationOut,
    FundAnalysisOut,
    FundCorroborationOut,
    FundDetailOut,
    FundHistoryOut,
    FundHistoryPointOut,
    FundHoldingOut,
    FundHoldingsOut,
    FundOut,
    PortfolioFundOut,
    PortfolioOut,
    PortfoliosOut,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/funds", tags=["funds"])

PERIOD_TO_TIMEDELTA: dict[str, timedelta] = {
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=370),
}


def _analysis_out(analysis) -> FundAnalysisOut | None:
    if analysis is None:
        return None
    return FundAnalysisOut(
        body_tr=analysis.body_tr,
        outlook=analysis.outlook,
        provider=analysis.provider,
        analysis_date=analysis.analysis_date,
    )


async def _fund_out(repo: FundRepository, fund: Fund) -> FundOut:
    trend_rows = await repo.trend(fund.id, points=30)
    latest = trend_rows[-1] if trend_rows else None
    delta_pct = None
    if len(trend_rows) >= 2 and trend_rows[-2].value:
        delta_pct = round(
            (trend_rows[-1].value - trend_rows[-2].value) / trend_rows[-2].value * 100, 2
        )
    return FundOut(
        symbol=fund.symbol,
        name=fund.name,
        market=fund.market,
        currency=fund.currency,
        issuer=fund.issuer,
        target_weight=fund.target_weight,
        value=latest.value if latest else None,
        as_of=latest.as_of if latest else None,
        delta_pct=delta_pct,
        trend=[r.value for r in trend_rows],
        verification_status=latest.verification_status if latest else None,
        metadata_verified=fund.metadata_verified,
    )


@router.get("", response_model=list[FundOut])
async def list_funds(db: AsyncSession = Depends(get_db)) -> list[FundOut]:
    repo = FundRepository(db)
    funds = await repo.list_all()
    if not funds:
        # First boot before any refresh: surface the catalog so the UI can
        # render the fund cards (with honest "no data yet" placeholders).
        from app.funds_catalog import FUND_CATALOG

        for spec in FUND_CATALOG:
            await repo.upsert_fund(spec)
        await db.commit()
        funds = await repo.list_all()
    return [await _fund_out(repo, fund) for fund in funds]


@router.get("/portfolio", response_model=PortfoliosOut)
async def get_portfolios(db: AsyncSession = Depends(get_db)) -> PortfoliosOut:
    from app.services.fund_service import weighted_1y_return

    repo = FundRepository(db)
    portfolios: dict[str, PortfolioOut] = {}

    for market, scope in ((MARKET_US, "portfolio_us"), (MARKET_TR, "portfolio_tr")):
        weighted, per_fund = await weighted_1y_return(db, market)
        member_out: list[PortfolioFundOut] = []
        for spec in specs_for_market(market):
            fund = await repo.get_by_symbol(spec.symbol)
            latest = await repo.latest_price(fund.id) if fund else None
            member_out.append(
                PortfolioFundOut(
                    symbol=spec.symbol,
                    name=fund.name if fund else spec.name,
                    target_weight=spec.target_weight,
                    value=latest.value if latest else None,
                    as_of=latest.as_of if latest else None,
                    return_1y_pct=per_fund.get(spec.symbol),
                    verification_status=latest.verification_status if latest else None,
                )
            )
        analysis = await repo.latest_analysis(scope)
        portfolios[market] = PortfolioOut(
            market=market,
            funds=member_out,
            weighted_return_1y_pct=weighted,
            analysis=_analysis_out(analysis),
        )

    return PortfoliosOut(us=portfolios[MARKET_US], tr=portfolios[MARKET_TR])


@router.post("/refresh", dependencies=[Depends(require_roles("admin", "editor"))])
async def trigger_funds_refresh(db: AsyncSession = Depends(get_db)) -> dict:
    """Manual refresh -- the same call the scheduled job makes."""
    from app.services.fund_analysis_service import regenerate_fund_analyses
    from app.services.fund_service import refresh_all_funds

    results = await refresh_all_funds(db)
    analyses = await regenerate_fund_analyses(db)
    return {"funds": results, "analyses": analyses}


@router.get("/{symbol}", response_model=FundDetailOut)
async def get_fund_detail(symbol: str, db: AsyncSession = Depends(get_db)) -> FundDetailOut:
    repo = FundRepository(db)
    fund = await repo.get_by_symbol(symbol)
    if fund is None:
        if get_fund_spec(symbol) is None:
            raise HTTPException(status_code=404, detail="Unknown fund")
        raise HTTPException(status_code=404, detail="Fund not initialized yet -- run a refresh")

    trend_rows = await repo.trend(fund.id, points=2)
    latest = trend_rows[-1] if trend_rows else None
    delta_pct = None
    if len(trend_rows) == 2 and trend_rows[0].value:
        delta_pct = round((trend_rows[1].value - trend_rows[0].value) / trend_rows[0].value * 100, 2)

    corroborations = []
    if latest is not None:
        corroborations = [
            FundCorroborationOut(
                source=c.source,
                source_url=c.source_url,
                value=c.value,
                as_of=c.as_of,
                diff_pct=round(abs(latest.value - c.value) / latest.value * 100, 3)
                if latest.value
                else 0.0,
            )
            for c in await repo.latest_corroborations(fund.id)
        ]

    analysis = await repo.latest_analysis("fund", fund.id)

    return FundDetailOut(
        symbol=fund.symbol,
        name=fund.name,
        market=fund.market,
        currency=fund.currency,
        issuer=fund.issuer,
        target_weight=fund.target_weight,
        expense_ratio=fund.expense_ratio,
        aum=fund.aum,
        aum_as_of=fund.aum_as_of,
        metadata_source=fund.metadata_source,
        metadata_verified=fund.metadata_verified,
        value=latest.value if latest else None,
        as_of=latest.as_of if latest else None,
        delta_pct=delta_pct,
        source=latest.source if latest else None,
        source_url=latest.source_url if latest else None,
        verification_status=latest.verification_status if latest else None,
        corroborations=corroborations,
        analysis=_analysis_out(analysis),
    )


@router.get("/{symbol}/history", response_model=FundHistoryOut)
async def get_fund_history(
    symbol: str,
    period: str = Query("1y", pattern="^(1m|3m|6m|1y)$"),
    db: AsyncSession = Depends(get_db),
) -> FundHistoryOut:
    repo = FundRepository(db)
    fund = await repo.get_by_symbol(symbol)
    if fund is None:
        raise HTTPException(status_code=404, detail="Unknown fund")

    since = datetime.now(timezone.utc) - PERIOD_TO_TIMEDELTA[period]
    rows = await repo.price_history(fund.id, since)
    return FundHistoryOut(
        symbol=fund.symbol,
        period=period,
        currency=fund.currency,
        points=[FundHistoryPointOut(as_of=r.as_of, value=r.value) for r in rows],
    )


@router.get("/{symbol}/holdings", response_model=FundHoldingsOut)
async def get_fund_holdings(symbol: str, db: AsyncSession = Depends(get_db)) -> FundHoldingsOut:
    repo = FundRepository(db)
    fund = await repo.get_by_symbol(symbol)
    if fund is None:
        raise HTTPException(status_code=404, detail="Unknown fund")

    holdings = await repo.latest_holdings(fund.id)
    allocations = await repo.latest_allocations(fund.id)
    first = holdings[0] if holdings else None

    return FundHoldingsOut(
        symbol=fund.symbol,
        as_of=first.as_of if first else None,
        source=first.source if first else None,
        verification_status=first.verification_status if first else None,
        is_top10_only=first.is_top10_only if first else False,
        holdings=[
            FundHoldingOut(
                rank=h.rank,
                ticker=h.ticker,
                holding_name=h.holding_name,
                weight_pct=h.weight_pct,
                sector=h.sector,
            )
            for h in holdings
        ],
        allocations=[
            FundAllocationOut(kind=a.kind, label=a.label, weight_pct=a.weight_pct)
            for a in allocations
        ],
        allocations_as_of=allocations[0].as_of if allocations else None,
    )
