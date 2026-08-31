"""Hand-curated rows for Kokpit's two reference tables (see app/models/curated.py).

Like app/ingest/sources_seed.py, this file *is* the source of truth: running
seed_curated_data() reconciles the database to exactly what's declared here,
updating a row that already exists (an institution revising its own forecast)
rather than duplicating it. Adding or editing an entry and opening a PR is the
review step -- there is no separate approval UI.

**IATA indicators.** Every figure below is read off the same verbatim IATA
*Global Outlook for Air Transport, June 2026* series already transcribed once
in app/ingest/historical_seed.py (Tables 4, 6 and 7), not re-researched --
reusing an already-cited source is safer than a second transcription that
could disagree with the first. `ebit` and `net_profit` are two rows because
IATA publishes two lines: earnings before interest and tax (operating profit)
and the post-tax bottom line. They are not close enough to stand in for each
other -- 2026 is $48.0bn of EBIT and $23.0bn of net profit -- so the table
carries both under the names the report uses, and neither is relabelled as the
other.

**Revision tracking.** IATA revises its own forecasts between editions, and on
the 2026 numbers the revision *is* the story: the June 2026 report halves the
net-profit forecast the December 2025 edition printed. Forecast rows therefore
carry the previous edition's figure alongside the current one (see the
`previous_*` columns in app/models/curated.py). Actual rows do not: a
measurement has no earlier forecast of itself, and back-filling one from a
forecast row would make the two kinds the schema keeps apart bleed together.

**Bank FX forecasts.** Each entry needs a real, individually-attributed,
currently-verifiable citation -- see the legal reasoning in
app/models/curated.py. Populated as verified.
"""
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.historical_seed import (
    EBIT_BN,
    LOAD_FACTOR_PCT,
    NET_PROFIT_BN,
    PASSENGERS_MILLION,
    RPK_BILLION,
)
from app.ingest.historical_seed import PUBLISHED_AT as IATA_PUBLISHED_AT
from app.ingest.historical_seed import SOURCE_URL as IATA_SOURCE_URL
from app.repositories.curated_repository import CuratedRepository

logger = get_logger(__name__)

_PUBLICATION_DATE = IATA_PUBLISHED_AT.date()
# YEARS in historical_seed.py is (2019 .. 2026); indices 6 and 7 are 2025/2026.
_ACTUAL_YEAR, _ACTUAL_IDX = 2025, 6
_FORECAST_YEAR, _FORECAST_IDX = 2026, 7

# The edition before the one everything above is transcribed from: IATA's
# *Global Outlook for Air Transport, December 2025*, published 2025-12-09. Only
# its 2026 forecasts are recorded, and only as comparators -- see "Revision
# tracking" in the module docstring.
_PREVIOUS_SOURCE_URL = (
    "https://www.iata.org/en/publications/economics/reports/"
    "global-outlook-for-air-transport-december-2025/"
)
_PREVIOUS_PUBLICATION_DATE = date(2025, 12, 9)

# metric -> what the December 2025 edition printed for full-year 2026.
# `rpk_growth` is the one entry not lifted straight off a table: December 2025
# published 4.9% as a growth rate, which is the same quantity _rpk_growth_pct
# derives below, so the pair is comparable. A metric absent from this map
# simply gets no revision line.
_PREVIOUS_2026_FORECAST: dict[str, float] = {
    "net_profit": 41.0,
    "ebit": 72.8,
    "load_factor": 83.8,
    "passenger_demand": 5202,
    "rpk_growth": 4.9,
}


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def _rpk_growth_pct(idx: int) -> float:
    """RPK growth from the transcribed RPK series.

    Derived rather than transcribed because IATA prints this one rounded to a
    single decimal (2.1% for 2025, 5.3% for 2026) while publishing the RPK
    levels the rate comes from. Keeping the derivation means the rate and the
    levels can never disagree by a rounding step, at the cost of showing 2.09
    and 5.33 where the report shows 2.1 and 5.3 -- the same arithmetic-on-a-
    citation trade historical_seed.py makes for ASK, yield, RASK and CASK.
    """
    return round((RPK_BILLION[idx] - RPK_BILLION[idx - 1]) / RPK_BILLION[idx - 1] * 100, 2)


def _revision(metric: str, kind: str) -> dict:
    """The previous edition's figure for a 2026 forecast row, or nothing.

    Actuals never get one: they are measurements, not restated projections.
    """
    if kind != "forecast" or metric not in _PREVIOUS_2026_FORECAST:
        return {}
    return dict(
        previous_value=_PREVIOUS_2026_FORECAST[metric],
        previous_publication_date=_PREVIOUS_PUBLICATION_DATE,
        previous_source_url=_PREVIOUS_SOURCE_URL,
    )


IATA_INDICATOR_ENTRIES: list[dict] = []
for _label, _year, _idx, _kind in (
    ("actual", _ACTUAL_YEAR, _ACTUAL_IDX, "actual"),
    ("forecast", _FORECAST_YEAR, _FORECAST_IDX, "forecast"),
):
    _start, _end = _year_bounds(_year)
    IATA_INDICATOR_ENTRIES.extend(
        [
            dict(
                metric="net_profit",
                kind=_kind,
                value=NET_PROFIT_BN[_idx],
                unit="USD milyar",
                period_start=_start,
                period_end=_end,
                period_label_tr=str(_year),
                publication_date=_PUBLICATION_DATE,
                source_url=IATA_SOURCE_URL,
                interpretation_tr=(
                    "Sektörün vergi sonrası net kârı -- IATA'nın manşet rakamı."
                    if _kind == "actual"
                    else (
                        "IATA, Orta Doğu kaynaklı aksamalar ve yüksek yakıt fiyatları nedeniyle "
                        "2026 net kâr tahminini 41 milyar dolardan 23 milyara indirdi; net kâr "
                        "marjı %2,0'a geriliyor."
                    )
                ),
                **_revision("net_profit", _kind),
            ),
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
                **_revision("ebit", _kind),
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
                **_revision("load_factor", _kind),
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
                **_revision("passenger_demand", _kind),
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
                **_revision("rpk_growth", _kind),
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
