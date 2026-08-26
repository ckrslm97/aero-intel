from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curated import FxForecast, IataIndicator


class CuratedRepository:
    """Reads and reconciles the two hand-curated tables (see
    app/models/curated.py). Reconciliation mirrors SourceRepository.ensure_seeded:
    the seed file in app/ingest/curated_seed.py is the source of truth, and
    re-running it updates a row that already exists rather than duplicating it.

    The natural key deliberately excludes `value` -- (institution, pair,
    horizon) or (metric, kind, period_end) identifies *which claim* a row
    makes; a bank revising its own Q4 2026 number is the same claim with a new
    value, not a second claim, so it must update the existing row.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_fx_forecast(
        self,
        *,
        institution: str,
        currency_pair: str,
        horizon_label: str,
        horizon_months: int | None,
        value: float,
        publication_date: date,
        source_url: str,
        note_tr: str | None = None,
        entered_by: str = "curated",
        reviewed_at: datetime | None = None,
    ) -> tuple[FxForecast, bool]:
        existing = (
            await self.db.execute(
                select(FxForecast).where(
                    FxForecast.institution == institution,
                    FxForecast.currency_pair == currency_pair,
                    FxForecast.horizon_label == horizon_label,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            row = FxForecast(
                institution=institution,
                currency_pair=currency_pair,
                horizon_label=horizon_label,
                horizon_months=horizon_months,
                value=value,
                publication_date=publication_date,
                source_url=source_url,
                note_tr=note_tr,
                entered_by=entered_by,
                reviewed_at=reviewed_at,
            )
            self.db.add(row)
            return row, True

        existing.horizon_months = horizon_months
        existing.value = value
        existing.publication_date = publication_date
        existing.source_url = source_url
        existing.note_tr = note_tr
        existing.entered_by = entered_by
        existing.reviewed_at = reviewed_at
        return existing, False

    async def upsert_iata_indicator(
        self,
        *,
        metric: str,
        kind: str,
        value: float,
        unit: str,
        period_start: date,
        period_end: date,
        period_label_tr: str,
        publication_date: date,
        source_url: str,
        region: str | None = None,
        interpretation_tr: str | None = None,
        entered_by: str = "curated",
        reviewed_at: datetime | None = None,
    ) -> tuple[IataIndicator, bool]:
        existing = (
            await self.db.execute(
                select(IataIndicator).where(
                    IataIndicator.metric == metric,
                    IataIndicator.kind == kind,
                    IataIndicator.period_end == period_end,
                    IataIndicator.region.is_(region) if region is None else IataIndicator.region == region,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            row = IataIndicator(
                metric=metric,
                kind=kind,
                value=value,
                unit=unit,
                period_start=period_start,
                period_end=period_end,
                period_label_tr=period_label_tr,
                region=region,
                publication_date=publication_date,
                source_url=source_url,
                interpretation_tr=interpretation_tr,
                entered_by=entered_by,
                reviewed_at=reviewed_at,
            )
            self.db.add(row)
            return row, True

        existing.value = value
        existing.unit = unit
        existing.period_start = period_start
        existing.period_label_tr = period_label_tr
        existing.publication_date = publication_date
        existing.source_url = source_url
        existing.interpretation_tr = interpretation_tr
        existing.entered_by = entered_by
        existing.reviewed_at = reviewed_at
        return existing, False

    async def fx_forecasts(
        self, *, currency_pair: str | None = None, horizon_months: int | None = None
    ) -> list[FxForecast]:
        query = select(FxForecast)
        if currency_pair is not None:
            query = query.where(FxForecast.currency_pair == currency_pair)
        if horizon_months is not None:
            query = query.where(FxForecast.horizon_months == horizon_months)
        query = query.order_by(FxForecast.currency_pair, FxForecast.publication_date.desc())
        return list((await self.db.execute(query)).scalars().all())

    async def iata_indicators(
        self, *, kind: str | None = None, region: str | None = None
    ) -> list[IataIndicator]:
        query = select(IataIndicator)
        if kind is not None:
            query = query.where(IataIndicator.kind == kind)
        if region is not None:
            query = query.where(IataIndicator.region == region)
        query = query.order_by(IataIndicator.metric, IataIndicator.period_end.desc())
        return list((await self.db.execute(query)).scalars().all())
