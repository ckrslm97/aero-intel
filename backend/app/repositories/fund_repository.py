"""DB access for the /invest module, KpiRepository style: thin, explicit
queries; the verification semantics live in fund_service, not here.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.funds_catalog import FundSpec
from app.models.fund import Fund, FundAllocation, FundAnalysis, FundHolding, FundPrice


class FundRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- funds ---------------------------------------------------------------

    async def get_by_symbol(self, symbol: str) -> Fund | None:
        result = await self.db.execute(select(Fund).where(Fund.symbol == symbol.upper()))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Fund]:
        result = await self.db.execute(select(Fund).order_by(Fund.market, Fund.target_weight.desc()))
        return list(result.scalars().all())

    async def upsert_fund(self, spec: FundSpec) -> Fund:
        """Ensure the catalog entry exists; catalog fields (weights) win, but
        runtime-enriched fields (official name, metadata) are preserved."""
        fund = await self.get_by_symbol(spec.symbol)
        if fund is None:
            fund = Fund(
                symbol=spec.symbol,
                market=spec.market,
                name=spec.name,
                currency=spec.currency,
                issuer=spec.issuer,
                target_weight=spec.target_weight,
            )
            self.db.add(fund)
            await self.db.flush()
        else:
            fund.market = spec.market
            fund.currency = spec.currency
            fund.target_weight = spec.target_weight
        return fund

    # -- prices --------------------------------------------------------------

    def record_price(
        self,
        fund_id: uuid.UUID,
        value: float,
        as_of: datetime,
        source: str,
        verification_status: str,
        source_url: str | None = None,
        is_primary: bool = True,
    ) -> FundPrice:
        price = FundPrice(
            fund_id=fund_id,
            value=value,
            as_of=as_of,
            source=source,
            source_url=source_url,
            is_primary=is_primary,
            verification_status=verification_status,
        )
        self.db.add(price)
        return price

    async def exists_price_at(self, fund_id: uuid.UUID, as_of: datetime) -> bool:
        """Idempotent backfill guard (KpiRepository.exists_at pattern)."""
        result = await self.db.execute(
            select(FundPrice.id)
            .where(FundPrice.fund_id == fund_id, FundPrice.as_of == as_of, FundPrice.is_primary.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def latest_price(self, fund_id: uuid.UUID) -> FundPrice | None:
        result = await self.db.execute(
            select(FundPrice)
            .where(FundPrice.fund_id == fund_id, FundPrice.is_primary.is_(True))
            .order_by(FundPrice.as_of.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def price_history(self, fund_id: uuid.UUID, since: datetime) -> list[FundPrice]:
        result = await self.db.execute(
            select(FundPrice)
            .where(FundPrice.fund_id == fund_id, FundPrice.is_primary.is_(True), FundPrice.as_of >= since)
            .order_by(FundPrice.as_of.asc())
        )
        return list(result.scalars().all())

    async def trend(self, fund_id: uuid.UUID, points: int = 30) -> list[FundPrice]:
        """Most recent `points` primary observations, oldest first (sparkline order)."""
        result = await self.db.execute(
            select(FundPrice)
            .where(FundPrice.fund_id == fund_id, FundPrice.is_primary.is_(True))
            .order_by(FundPrice.as_of.desc())
            .limit(points)
        )
        return list(reversed(result.scalars().all()))

    async def latest_corroborations(self, fund_id: uuid.UUID) -> list[FundPrice]:
        """Most recent secondary-source readings, one per distinct source."""
        result = await self.db.execute(
            select(FundPrice)
            .where(FundPrice.fund_id == fund_id, FundPrice.is_primary.is_(False))
            .order_by(FundPrice.as_of.desc())
            .limit(5)
        )
        seen: set[str] = set()
        rows: list[FundPrice] = []
        for price in result.scalars().all():
            if price.source in seen:
                continue
            seen.add(price.source)
            rows.append(price)
        return rows

    # -- holdings / allocations ----------------------------------------------

    async def replace_holdings(self, fund_id: uuid.UUID, as_of: date, holdings: list[FundHolding]) -> None:
        """Snapshot semantics: re-running a refresh for the same file date
        replaces that date's rows instead of duplicating them."""
        await self.db.execute(
            delete(FundHolding).where(FundHolding.fund_id == fund_id, FundHolding.as_of == as_of)
        )
        self.db.add_all(holdings)

    async def latest_holdings(self, fund_id: uuid.UUID) -> list[FundHolding]:
        latest_date = await self.db.execute(
            select(FundHolding.as_of)
            .where(FundHolding.fund_id == fund_id)
            .order_by(FundHolding.as_of.desc())
            .limit(1)
        )
        as_of = latest_date.scalar_one_or_none()
        if as_of is None:
            return []
        result = await self.db.execute(
            select(FundHolding)
            .where(FundHolding.fund_id == fund_id, FundHolding.as_of == as_of)
            .order_by(FundHolding.rank.asc())
        )
        return list(result.scalars().all())

    async def replace_allocations(self, fund_id: uuid.UUID, as_of: date, slices: list[FundAllocation]) -> None:
        await self.db.execute(
            delete(FundAllocation).where(FundAllocation.fund_id == fund_id, FundAllocation.as_of == as_of)
        )
        self.db.add_all(slices)

    async def latest_allocations(self, fund_id: uuid.UUID) -> list[FundAllocation]:
        latest_date = await self.db.execute(
            select(FundAllocation.as_of)
            .where(FundAllocation.fund_id == fund_id)
            .order_by(FundAllocation.as_of.desc())
            .limit(1)
        )
        as_of = latest_date.scalar_one_or_none()
        if as_of is None:
            return []
        result = await self.db.execute(
            select(FundAllocation)
            .where(FundAllocation.fund_id == fund_id, FundAllocation.as_of == as_of)
            .order_by(FundAllocation.weight_pct.desc())
        )
        return list(result.scalars().all())

    # -- analyses ------------------------------------------------------------

    async def latest_analysis(self, scope: str, fund_id: uuid.UUID | None = None) -> FundAnalysis | None:
        result = await self.db.execute(
            select(FundAnalysis)
            .where(FundAnalysis.scope == scope, FundAnalysis.fund_id == fund_id)
            .order_by(FundAnalysis.analysis_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_analysis(
        self,
        scope: str,
        fund_id: uuid.UUID | None,
        analysis_date: date,
        body_tr: str,
        outlook: str,
        provider: str,
        input_fingerprint: str,
    ) -> FundAnalysis:
        result = await self.db.execute(
            select(FundAnalysis).where(
                FundAnalysis.scope == scope,
                FundAnalysis.fund_id == fund_id,
                FundAnalysis.analysis_date == analysis_date,
            )
        )
        analysis = result.scalar_one_or_none()
        if analysis is None:
            analysis = FundAnalysis(
                scope=scope,
                fund_id=fund_id,
                analysis_date=analysis_date,
                body_tr=body_tr,
                outlook=outlook,
                provider=provider,
                input_fingerprint=input_fingerprint,
            )
            self.db.add(analysis)
        else:
            analysis.body_tr = body_tr
            analysis.outlook = outlook
            analysis.provider = provider
            analysis.input_fingerprint = input_fingerprint
        return analysis
