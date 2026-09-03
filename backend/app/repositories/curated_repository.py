import calendar
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curated import FxForecast, IataIndicator


def forecast_target_date(publication_date: date, horizon_months: int | None) -> date | None:
    """The date an institution's own horizon lands on, or None.

    None when `horizon_months` is NULL, which is not an edge case: a bank
    publishing "end-2026", "year-end" or "Q4 2026" writes a horizon this table
    deliberately refuses to rewrite into a month count (see the module
    docstring in app/models/curated.py -- silently mapping one onto a tidy
    column would be our interpolation presented as their forecast). So the
    answer is genuinely unknown, and it is returned as unknown.

    Calendar arithmetic, clamped to the month's length, so a 31 August + 6m
    lands on 28/29 February rather than raising.
    """
    if horizon_months is None:
        return None
    months = publication_date.month - 1 + horizon_months
    year = publication_date.year + months // 12
    month = months % 12 + 1
    return date(year, month, min(publication_date.day, calendar.monthrange(year, month)[1]))


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
        previous_value: float | None = None,
        previous_publication_date: date | None = None,
        previous_source_url: str | None = None,
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
                previous_value=previous_value,
                previous_publication_date=previous_publication_date,
                previous_source_url=previous_source_url,
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
        # Assigned unconditionally, including back to None: the seed file is the
        # source of truth, so dropping a `previous_*` from it must clear the
        # stored one rather than leave a stale revision line on the card.
        existing.previous_value = previous_value
        existing.previous_publication_date = previous_publication_date
        existing.previous_source_url = previous_source_url
        return existing, False

    async def fx_forecasts(
        self,
        *,
        currency_pair: str | None = None,
        horizon_months: int | None = None,
        only_upcoming: bool = False,
    ) -> list[FxForecast]:
        """The curated bank forecasts, newest publication first.

        `only_upcoming` drops rows whose own horizon has already ELAPSED. A
        bank's "+3 months" published in March is a claim about June, and in
        September it is a claim about the past -- still a true record of what
        was said, and still worth keeping in the table, but no longer a
        statement about where the rate is going. Kokpit's Kur Riski tile asks
        for it because that tile is about the road ahead; the /kokpit forecast
        table does not, because it is a record of who said what.

        Nothing is dropped on a guess. A row whose `horizon_months` is NULL
        cannot be dated at all (see `forecast_target_date`), so it survives the
        filter: refusing to publish a claim we cannot prove is stale would be
        acting on an absence of evidence.

        Applied in Python rather than as SQL date arithmetic: the table is a
        hand-curated few dozen rows, the month-add is calendar arithmetic that
        already exists once above, and an expression like
        `publication_date + make_interval(months => horizon_months)` returns
        NULL for exactly the rows that must be kept -- which would have
        silently inverted the rule.
        """
        query = select(FxForecast)
        if currency_pair is not None:
            query = query.where(FxForecast.currency_pair == currency_pair)
        if horizon_months is not None:
            query = query.where(FxForecast.horizon_months == horizon_months)
        query = query.order_by(FxForecast.currency_pair, FxForecast.publication_date.desc())
        rows = list((await self.db.execute(query)).scalars().all())
        if not only_upcoming:
            return rows
        today = datetime.now(timezone.utc).date()
        return [
            row
            for row in rows
            if (target := forecast_target_date(row.publication_date, row.horizon_months)) is None
            or target >= today
        ]

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
