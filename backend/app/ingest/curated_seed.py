"""Hand-curated rows for Kokpit's two reference tables (see app/models/curated.py).

Like app/ingest/sources_seed.py, this file *is* the source of truth: running
seed_curated_data() reconciles the database to exactly what's declared here,
updating a row that already exists (an institution revising its own forecast)
rather than duplicating it. Adding or editing an entry and opening a PR is the
review step -- there is no separate approval UI.

**IATA indicators.** Every figure below is read off the same verbatim IATA
*Global Outlook for Air Transport, June 2026* series already transcribed once
in app/ingest/historical_seed.py (Tables 4 and 6), not re-researched --
reusing an already-cited source is safer than a second transcription that
could disagree with the first. `ebit` is named for exactly what IATA reports
(earnings before interest and tax, i.e. operating profit) rather than
"net_profit" -- the report's net-profit line is not one of the figures
transcribed there, and mislabelling EBIT as net profit would misstate a real
number rather than omit one.

**Bank FX forecasts.** Each entry needs a real, individually-attributed,
currently-verifiable citation -- see the legal reasoning in
app/models/curated.py. Populated as verified.
"""
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.historical_seed import EBIT_BN, LOAD_FACTOR_PCT, PASSENGERS_MILLION, RPK_BILLION
from app.ingest.historical_seed import PUBLISHED_AT as IATA_PUBLISHED_AT
from app.ingest.historical_seed import SOURCE_URL as IATA_SOURCE_URL
from app.repositories.curated_repository import CuratedRepository

logger = get_logger(__name__)

_PUBLICATION_DATE = IATA_PUBLISHED_AT.date()
# YEARS in historical_seed.py is (2019 .. 2026); indices 6 and 7 are 2025/2026.
_ACTUAL_YEAR, _ACTUAL_IDX = 2025, 6
_FORECAST_YEAR, _FORECAST_IDX = 2026, 7


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def _rpk_growth_pct(idx: int) -> float:
    return round((RPK_BILLION[idx] - RPK_BILLION[idx - 1]) / RPK_BILLION[idx - 1] * 100, 2)


IATA_INDICATOR_ENTRIES: list[dict] = []
for _label, _year, _idx, _kind in (
    ("actual", _ACTUAL_YEAR, _ACTUAL_IDX, "actual"),
    ("forecast", _FORECAST_YEAR, _FORECAST_IDX, "forecast"),
):
    _start, _end = _year_bounds(_year)
    IATA_INDICATOR_ENTRIES.extend(
        [
            dict(
                metric="ebit",
                kind=_kind,
                value=EBIT_BN[_idx],
                unit="USD milyar",
                period_start=_start,
                period_end=_end,
                period_label_tr=str(_year),
                publication_date=_PUBLICATION_DATE,
                source_url=IATA_SOURCE_URL,
                interpretation_tr=(
                    "Sektörün faiz ve vergi öncesi kârı (EBIT) -- IATA'nın net kâr değil, "
                    "işletme kârı olarak raporladığı rakam."
                ),
            ),
            dict(
                metric="load_factor",
                kind=_kind,
                value=LOAD_FACTOR_PCT[_idx],
                unit="%",
                period_start=_start,
                period_end=_end,
                period_label_tr=str(_year),
                publication_date=_PUBLICATION_DATE,
                source_url=IATA_SOURCE_URL,
                interpretation_tr="Küresel doluluk oranı (RPK/ASK) -- kapasite kullanım verimliliği.",
            ),
            dict(
                metric="passenger_demand",
                kind=_kind,
                value=PASSENGERS_MILLION[_idx],
                unit="milyon yolcu",
                period_start=_start,
                period_end=_end,
                period_label_tr=str(_year),
                publication_date=_PUBLICATION_DATE,
                source_url=IATA_SOURCE_URL,
                interpretation_tr="Yıllık toplam yolcu sayısı.",
            ),
            dict(
                metric="rpk_growth",
                kind=_kind,
                value=_rpk_growth_pct(_idx),
                unit="%",
                period_start=_start,
                period_end=_end,
                period_label_tr=str(_year),
                publication_date=_PUBLICATION_DATE,
                source_url=IATA_SOURCE_URL,
                interpretation_tr="Bir önceki yıla göre RPK (yolcu-km) büyümesi -- talep göstergesi.",
            ),
        ]
    )


# Each entry needs a real, individually-attributed, currently-verifiable
# citation -- see the legal reasoning in app/models/curated.py's module
# docstring. institution/currency_pair/horizon_label are the natural key: a
# bank revising its own number updates this same entry, not a new one.
#
# horizon_months is left None wherever the institution's own label isn't
# itself an explicit month count ("Q4 2026", "end-2026", "year-end") --
# converting those to a number would be our arithmetic presented as their
# forecast, the exact mistake the module docstring warns against. Danske's
# own "+3m"/"+12m" columns are the one label here precise enough to carry one.
#
# A few real, verifiable data points found during research were deliberately
# left out: Goldman Sachs' most recent point figures for USD/TRY are dated
# 2025-07-20 (already past their own 12-month horizon) and ING's USD/CNY
# figure is a range ("6.85-7.25"), not a point forecast this schema's single
# `value` field can hold without misrepresenting it.
_DANSKE_URL = (
    "https://research.danskebank.com/link/FXForecastUpdate210826/"
    "$file/FX%20ForecastUpdate_210826.pdf"
)
_DANSKE_DATE = date(2026, 8, 21)
_ING_URL = "https://think.ing.com/articles/g10-fx-outlook-2026/"
_ING_DATE = date(2025, 11, 10)

FX_FORECAST_ENTRIES: list[dict] = [
    dict(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+3m",
        horizon_months=3,
        value=52.00,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
    dict(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.00,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
    dict(
        institution="JPMorgan",
        currency_pair="USD/TRY",
        horizon_label="end-2026",
        horizon_months=None,
        value=51.4,
        publication_date=date(2026, 7, 13),
        source_url="https://www.turkiyetoday.com/business/tourism-boom-keeps-pressure-off-turkish-lira-jpmorgan-says-3223844",
    ),
    dict(
        institution="Garanti BBVA Yatırım",
        currency_pair="USD/TRY",
        horizon_label="year-end",
        horizon_months=None,
        value=52.0,
        publication_date=date(2026, 6, 25),
        source_url="https://www.turkiyetoday.com/business/global-banks-stay-bullish-on-turkish-lira-as-policymakers-remain-cautious-3222659",
    ),
    dict(
        institution="Danske Bank",
        currency_pair="EUR/USD",
        horizon_label="+12m",
        horizon_months=12,
        value=1.12,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
    dict(
        institution="ING",
        currency_pair="EUR/USD",
        horizon_label="Q4 2026",
        horizon_months=None,
        value=1.22,
        publication_date=_ING_DATE,
        source_url=_ING_URL,
    ),
    dict(
        institution="Danske Bank",
        currency_pair="USD/JPY",
        horizon_label="+12m",
        horizon_months=12,
        value=155.0,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
    dict(
        institution="ING",
        currency_pair="USD/JPY",
        horizon_label="Q4 2026",
        horizon_months=None,
        value=148.00,
        publication_date=_ING_DATE,
        source_url=_ING_URL,
    ),
    dict(
        institution="Danske Bank",
        currency_pair="EUR/GBP",
        horizon_label="+12m",
        horizon_months=12,
        value=0.87,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
    dict(
        institution="ING",
        currency_pair="EUR/GBP",
        horizon_label="Q4 2026",
        horizon_months=None,
        value=0.90,
        publication_date=_ING_DATE,
        source_url=_ING_URL,
    ),
    dict(
        institution="Danske Bank",
        currency_pair="USD/CNY",
        horizon_label="+12m",
        horizon_months=12,
        value=6.60,
        publication_date=_DANSKE_DATE,
        source_url=_DANSKE_URL,
    ),
]


async def seed_curated_data(db: AsyncSession) -> dict[str, int]:
    repo = CuratedRepository(db)
    fx_new = 0
    for entry in FX_FORECAST_ENTRIES:
        _, was_new = await repo.upsert_fx_forecast(**entry)
        if was_new:
            fx_new += 1

    iata_new = 0
    for entry in IATA_INDICATOR_ENTRIES:
        _, was_new = await repo.upsert_iata_indicator(**entry)
        if was_new:
            iata_new += 1

    await db.commit()
    logger.info("curated_data_seeded", fx_forecasts_new=fx_new, iata_indicators_new=iata_new)
    return {"fx_forecasts_new": fx_new, "iata_indicators_new": iata_new}
