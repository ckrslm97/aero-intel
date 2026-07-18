"""Refreshes the /invest module's fund data with per-row verification.

The rule the whole module lives by: **no number is presented as verified unless
two independent sources agreed on it**. Every price and holdings row is stored
with a verification_status the UI renders as a badge:

* `verified` -- a second, independent source agreed within tolerance
  (price: <=1% relative diff; holdings: <=2pp absolute per name).
* `official_single_source` -- TEFAS. The regulator-run platform is the
  authoritative record for Turkish funds and has no independent mirror
  (fundturkey.com.tr is the same backend), so "cross-verified" is impossible
  by construction; saying so honestly beats pretending.
* `single_source` -- the cross-check source didn't answer. The number is shown,
  labeled unconfirmed.
* `discrepancy` -- sources disagreed beyond tolerance. Surfaced, never hidden.

Each fund refreshes inside its own try/except so one dead source never blocks
the rest (same isolation principle as ingestion adapters).
"""
import asyncio
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.funds_catalog import (
    FUND_CATALOG,
    HOLDINGS_SOURCE_ARK,
    HOLDINGS_SOURCE_SSGA,
    HOLDINGS_SOURCE_VANGUARD,
    MARKET_TR,
    MARKET_US,
    FundSpec,
)
from app.ingest.funds.base import FundProfile, HoldingsSnapshot
from app.models.fund import (
    DISCREPANCY,
    OFFICIAL_SINGLE_SOURCE,
    SINGLE_SOURCE,
    VERIFIED,
    Fund,
    FundAllocation,
    FundHolding,
)
from app.repositories.fund_repository import FundRepository

logger = get_logger(__name__)

PRICE_TOLERANCE_PCT = 1.0  # two sources within 1% -> verified
HOLDING_TOLERANCE_PP = 2.0  # per-name weight within 2 percentage points -> verified
TEFAS_REQUEST_GAP_SECONDS = 10  # ~6 req/min platform rate limit

YAHOO_QUOTE_PAGE = "https://finance.yahoo.com/quote/{symbol}"
TEFAS_FUND_PAGE = "https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={symbol}"


def _price_status(primary: float, cross: float | None) -> str:
    if cross is None:
        return SINGLE_SOURCE
    diff_pct = abs(primary - cross) / primary * 100 if primary else 100.0
    return VERIFIED if diff_pct <= PRICE_TOLERANCE_PCT else DISCREPANCY


def _holdings_status(snapshot: HoldingsSnapshot, profile: FundProfile | None) -> str:
    """Cross-check issuer holdings against Yahoo's top-10 by name-insensitive
    ticker match. Tolerant of file-date drift between the two sources."""
    if profile is None or not profile.top_holdings:
        return SINGLE_SOURCE
    by_ticker = {row.ticker.upper(): row.weight_pct for row in snapshot.rows if row.ticker}
    compared = 0
    agreed = 0
    for yahoo_row in profile.top_holdings:
        if not yahoo_row.ticker:
            continue
        issuer_weight = by_ticker.get(yahoo_row.ticker.upper())
        if issuer_weight is None:
            continue
        compared += 1
        if abs(issuer_weight - yahoo_row.weight_pct) <= HOLDING_TOLERANCE_PP:
            agreed += 1
    if compared == 0:
        return SINGLE_SOURCE
    # Majority agreement verifies the snapshot; systematic disagreement is a
    # discrepancy worth surfacing even if a name or two drifted.
    return VERIFIED if agreed / compared >= 0.7 else DISCREPANCY


async def _fetch_issuer_holdings(spec: FundSpec) -> HoldingsSnapshot | None:
    """Dispatch to the issuer adapter named in the catalog. Lazy imports keep
    optional parser deps (openpyxl) out of module import time."""
    settings = get_settings()
    if spec.holdings_source == HOLDINGS_SOURCE_SSGA:
        from app.ingest.funds.ssga import fetch_ssga_holdings

        return await fetch_ssga_holdings(settings.ssga_holdings_base_url, spec.symbol)
    if spec.holdings_source == HOLDINGS_SOURCE_ARK:
        from app.ingest.funds.ark import fetch_arkg_holdings

        return await fetch_arkg_holdings(settings.ark_holdings_base_url)
    if spec.holdings_source == HOLDINGS_SOURCE_VANGUARD:
        from app.ingest.funds.vanguard import fetch_vht_holdings

        return await fetch_vht_holdings()
    return None


def _profile_to_snapshot(profile: FundProfile, symbol: str) -> HoldingsSnapshot | None:
    """Yahoo top-10 as a last-resort holdings snapshot (VHT fallback). Dated
    'today' because Yahoo doesn't state the underlying file date -- another
    reason it stays labeled single_source."""
    if not profile.top_holdings:
        return None
    return HoldingsSnapshot(
        as_of=datetime.now(timezone.utc).date(),
        source="yahoo_quote_summary",
        source_url=YAHOO_QUOTE_PAGE.format(symbol=symbol),
        rows=profile.top_holdings,
        is_top10_only=True,
    )


async def refresh_us_fund(db: AsyncSession, spec: FundSpec) -> dict:
    from app.ingest.funds.stockanalysis import fetch_price_cross_check
    from app.ingest.funds.yahoo import fetch_fund_profile
    from app.ingest.markets import fetch_history

    settings = get_settings()
    repo = FundRepository(db)
    fund = await repo.upsert_fund(spec)
    summary: dict = {"symbol": spec.symbol, "prices_added": 0, "holdings": None, "price_status": None}

    # -- price history (1y daily) + latest-close cross-check -----------------
    points = await fetch_history(settings.yahoo_finance_base_url, spec.symbol, "1y_daily")
    if points:
        cross = await fetch_price_cross_check(settings.stockanalysis_base_url, spec.symbol)
        latest_ts, latest_close = points[-1]
        status_latest = _price_status(latest_close, cross)

        for ts, close in points:
            if await repo.exists_price_at(fund.id, ts):
                continue
            # Only the newest point had a live cross-check; history rows carry
            # single_source rather than inheriting a verification they never got.
            repo.record_price(
                fund.id,
                close,
                ts,
                "Yahoo Finance",
                status_latest if ts == latest_ts else SINGLE_SOURCE,
                source_url=YAHOO_QUOTE_PAGE.format(symbol=spec.symbol),
            )
            summary["prices_added"] += 1

        if cross is not None:
            repo.record_price(
                fund.id,
                cross,
                datetime.now(timezone.utc),
                "stockanalysis.com",
                status_latest,
                source_url=f"https://stockanalysis.com/etf/{spec.symbol.lower()}/",
                is_primary=False,
            )
        summary["price_status"] = status_latest
        logger.info(
            "fund_price_refresh",
            symbol=spec.symbol,
            added=summary["prices_added"],
            status=status_latest,
            cross_check=cross,
        )
    else:
        logger.warning("fund_price_refresh_empty", symbol=spec.symbol)

    # -- holdings: issuer file, cross-checked against Yahoo top-10 -----------
    profile = await fetch_fund_profile(settings.yahoo_quote_summary_base_url, spec.symbol)
    snapshot = await _fetch_issuer_holdings(spec)
    if snapshot is None and profile is not None:
        snapshot = _profile_to_snapshot(profile, spec.symbol)

    if snapshot is not None and snapshot.rows:
        status = SINGLE_SOURCE if snapshot.is_top10_only else _holdings_status(snapshot, profile)
        rows = [
            FundHolding(
                fund_id=fund.id,
                as_of=snapshot.as_of,
                rank=row.rank,
                ticker=row.ticker,
                holding_name=row.holding_name,
                weight_pct=row.weight_pct,
                sector=row.sector,
                source=snapshot.source,
                verification_status=status,
                is_top10_only=snapshot.is_top10_only,
            )
            for row in snapshot.rows
        ]
        await repo.replace_holdings(fund.id, snapshot.as_of, rows)
        summary["holdings"] = {"count": len(rows), "status": status, "source": snapshot.source}

        # Sector rollup from full holdings (skip for top-10-only: rolling up a
        # tenth of a fund would present a fake allocation).
        if not snapshot.is_top10_only:
            sector_weights: dict[str, float] = {}
            for row in snapshot.rows:
                if row.sector:
                    sector_weights[row.sector] = sector_weights.get(row.sector, 0.0) + row.weight_pct
            if sector_weights:
                await repo.replace_allocations(
                    fund.id,
                    snapshot.as_of,
                    [
                        FundAllocation(
                            fund_id=fund.id,
                            as_of=snapshot.as_of,
                            kind="sector",
                            label=label,
                            weight_pct=round(weight, 2),
                            source=snapshot.source,
                        )
                        for label, weight in sorted(sector_weights.items(), key=lambda kv: -kv[1])
                    ],
                )
        elif profile is not None and profile.sector_weights:
            # Yahoo's own sector weights cover the whole fund even when the
            # holdings list is top-10 -- usable, but still single-source.
            await repo.replace_allocations(
                fund.id,
                snapshot.as_of,
                [
                    FundAllocation(
                        fund_id=fund.id,
                        as_of=snapshot.as_of,
                        kind="sector",
                        label=label,
                        weight_pct=round(weight, 2),
                        source="yahoo_quote_summary",
                    )
                    for label, weight in profile.sector_weights
                ],
            )
    else:
        logger.warning("fund_holdings_refresh_empty", symbol=spec.symbol)

    # -- metadata -------------------------------------------------------------
    if profile is not None and profile.expense_ratio is not None:
        fund.expense_ratio = profile.expense_ratio
        fund.metadata_source = "yahoo_quote_summary"
        # verified only if a second source stated the same figure; Yahoo alone isn't enough
        fund.metadata_verified = False
    if profile is not None and profile.aum is not None:
        fund.aum = profile.aum
        fund.aum_as_of = datetime.now(timezone.utc).date()

    return summary


async def refresh_tr_fund(db: AsyncSession, spec: FundSpec) -> dict:
    from app.ingest.funds.tefas import fetch_tefas_allocation, fetch_tefas_info

    settings = get_settings()
    repo = FundRepository(db)
    fund = await repo.upsert_fund(spec)
    summary: dict = {"symbol": spec.symbol, "prices_added": 0, "allocation": None}

    info = await fetch_tefas_info(settings.tefas_base_url, spec.symbol, months=12)
    if info is not None and info.points:
        for point in info.points:
            if await repo.exists_price_at(fund.id, point.as_of):
                continue
            repo.record_price(
                fund.id,
                point.nav,
                point.as_of,
                "TEFAS",
                OFFICIAL_SINGLE_SOURCE,
                source_url=TEFAS_FUND_PAGE.format(symbol=spec.symbol),
            )
            summary["prices_added"] += 1

        # The official FONUNVAN replaces the catalog placeholder -- the one
        # metadata field TEFAS itself is authoritative for.
        if info.fund_title:
            fund.name = info.fund_title
            fund.metadata_source = "TEFAS"
            fund.metadata_verified = True
        if info.aum is not None:
            fund.aum = info.aum
            fund.aum_as_of = info.points[-1].as_of.date()
        logger.info("fund_tefas_refresh", symbol=spec.symbol, added=summary["prices_added"])
    else:
        logger.warning("fund_tefas_refresh_empty", symbol=spec.symbol)

    await asyncio.sleep(TEFAS_REQUEST_GAP_SECONDS)

    allocation = await fetch_tefas_allocation(settings.tefas_base_url, spec.symbol)
    if allocation is not None:
        as_of, slices = allocation
        if slices:
            await repo.replace_allocations(
                fund.id,
                as_of,
                [
                    FundAllocation(
                        fund_id=fund.id,
                        as_of=as_of,
                        kind="asset_class",
                        label=s.label,
                        weight_pct=s.weight_pct,
                        source="TEFAS",
                    )
                    for s in slices
                ],
            )
            summary["allocation"] = {"count": len(slices), "as_of": as_of.isoformat()}

    return summary


async def refresh_all_funds(db: AsyncSession) -> dict:
    """Refresh every catalog fund, isolating failures per fund. TR funds are
    paced (TEFAS rate limit); the gap sleep lives in refresh_tr_fund."""
    results: dict = {"refreshed": [], "failed": []}
    for spec in FUND_CATALOG:
        try:
            if spec.market == MARKET_US:
                summary = await refresh_us_fund(db, spec)
            else:
                summary = await refresh_tr_fund(db, spec)
            await db.commit()
            results["refreshed"].append(summary)
        except Exception as exc:  # noqa: BLE001 -- one fund must never block the rest
            await db.rollback()
            logger.warning("fund_refresh_failed", symbol=spec.symbol, error=str(exc))
            results["failed"].append(spec.symbol)
    logger.info(
        "funds_refresh_summary",
        refreshed=len(results["refreshed"]),
        failed=results["failed"],
    )
    return results


def portfolio_markets() -> list[str]:
    return [MARKET_US, MARKET_TR]


async def weighted_1y_return(db: AsyncSession, market: str) -> tuple[float | None, dict[str, float | None]]:
    """Weighted 1y return for the user's example allocation. Returns (portfolio
    figure, per-symbol returns). The portfolio figure is None unless EVERY
    member fund has usable 1y history -- a partial sum would silently misstate
    the portfolio, so honesty wins over completeness."""
    from app.funds_catalog import specs_for_market

    repo = FundRepository(db)
    per_fund: dict[str, float | None] = {}
    weighted_sum = 0.0
    complete = True

    for spec in specs_for_market(market):
        fund = await repo.get_by_symbol(spec.symbol)
        ret = await _one_year_return(repo, fund) if fund else None
        per_fund[spec.symbol] = ret
        if ret is None:
            complete = False
        else:
            weighted_sum += spec.target_weight * ret

    return (round(weighted_sum, 2) if complete else None), per_fund


async def _one_year_return(repo: FundRepository, fund: Fund) -> float | None:
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=370)
    history = await repo.price_history(fund.id, since)
    if len(history) < 2:
        return None
    first, last = history[0], history[-1]
    # A "1y" return computed off a few weeks of accumulated data would lie --
    # require the series to actually start ~a year ago.
    if (last.as_of - first.as_of).days < 300:
        return None
    if not first.value:
        return None
    return round((last.value - first.value) / first.value * 100, 2)
