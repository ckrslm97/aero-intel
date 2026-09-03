"""Dashboard KPIs -- returns the latest value + recent trend per metric, in a
fixed display order. See kpi_service.py for what's real vs. derived/estimated.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.config import get_settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.ingest.historical_seed import year_kind
from app.ingest.markets import fetch_history
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kpi import (
    CORROBORATION_DIVERGES,
    CORROBORATION_INCOMPARABLE,
    CORROBORATION_MATCH,
    CORROBORATION_VERDICT_LABELS_TR,
    KpiCorroborationOut,
    KpiDetailOut,
    KpiHistoryPointOut,
    KpiOut,
)
from app.services.kpi_service import (
    JET_FUEL_CRACK_SPREAD_USD,
    LY_SUFFIX,
    PUBLISHED_ESTIMATE_KEYS,
)
from app.taxonomy import PERIOD_KIND_LABELS_TR

logger = get_logger(__name__)

router = APIRouter(prefix="/kpis", tags=["kpis"])

# metric_key -> (display label, whether an increase is desirable)
KPI_DISPLAY: dict[str, tuple[str, bool]] = {
    "flights_airborne": ("Şu anda havada olan uçuşlar", True),
    "flights_today": ("Bugünkü uçuşlar", True),
    "passengers_ytd": ("Yolcu sayısı (2026 tahmini)", True),
    "load_factor": ("Küresel doluluk oranı", True),
    "fuel_price": ("Jet yakıtı fiyatı", False),
    "oil_price": ("Brent petrol", False),
    "wti_price": ("WTI ham petrol", False),
    "natgas_price": ("Doğal gaz (Henry Hub)", False),
    # Every live pair Kokpit's market strip prints, so each of its cards has a
    # real /kpi/<metric_key> page to open rather than a dead link. `up_is_good`
    # is False across the board only because KpiOut has no third state: a
    # currency pair moving is neither good nor bad, and the surfaces that
    # render these (market-strip.tsx, fx-board deltas) use a NEUTRAL delta tone
    # for exactly that reason. Nothing on Kokpit colours an FX move.
    "fx_usd_try": ("USD/TRY", False),
    "fx_eur_try": ("EUR/TRY", False),
    "fx_eur_usd": ("EUR/USD", False),
    "fx_gbp_try": ("GBP/TRY", False),
    "fx_gbp_usd": ("GBP/USD", False),
    "fx_usd_jpy": ("USD/JPY", False),
    "fx_eur_gbp": ("EUR/GBP", False),
    "fx_usd_cny": ("USD/CNY", False),
    "departures": ("Uçuş kalkışları (yıllık)", True),
    "total_aviation_revenue_ytd": ("Havacılık geliri (yolcu + ek gelir)", True),
    "passenger_revenue_ytd": ("Yolcu geliri", True),
    "ancillary_revenue_ytd": ("Ek gelir", True),
    "rask": ("RASK (birim gelir)", True),
    "cask": ("CASK (birim maliyet)", False),
    "yield_per_rpk": ("Getiri (Yield)", True),
    "ask": ("ASK (kapasite)", True),
    "rpk": ("RPK (trafik)", True),
}

# metric_key -> Yahoo Finance symbol, for metrics with a real historical
# archive we can pull on demand rather than waiting for our own history to
# accumulate. "fuel_price" reuses oil's history (see get_kpi_detail).
#
# Every pair added here gets a real multi-year chart on its detail page from
# the first minute it exists, which is the whole point: the newly-added
# EUR/TRY and GBP/USD have no stored history of OUR own yet, and without an
# external archive their detail pages would have shown a single point.
YAHOO_HISTORY_SYMBOLS: dict[str, str] = {
    "oil_price": "BZ=F",
    "wti_price": "CL=F",
    "natgas_price": "NG=F",
    "fx_usd_try": "TRY=X",
    "fx_eur_try": "EURTRY=X",
    "fx_eur_usd": "EURUSD=X",
    # Without this the /kpi/fx_gbp_try detail page would draw a single point:
    # the history fetch is keyed off this map, not off LIVE_FX_PAIRS.
    "fx_gbp_try": "GBPTRY=X",
    "fx_gbp_usd": "GBPUSD=X",
    "fx_usd_jpy": "JPY=X",
    "fx_eur_gbp": "EURGBP=X",
    "fx_usd_cny": "CNY=X",
}

PERIOD_TO_TIMEDELTA: dict[str, timedelta] = {
    "1w": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}

# Last-year comparison: 2025 is the last completed year in the seeded IATA
# series (see ingest/historical_seed.py); market metrics compare against the
# price a year ago instead.
LY_YEAR = 2025
LY_COMPARISON_LABEL = "2025'e göre"
PREVIOUS_COMPARISON_LABEL = "önceki ölçüme göre"

# ---------------------------------------------------------------------------
# WHAT PERIOD A KPI'S VALUE DESCRIBES
#
# Two populations share this endpoint and they are not the same kind of number.
# Brent's card carries a price that existed at a moment; load_factor's carries
# IATA's projection for a calendar year that has not finished. The page drew
# both identically -- value, delta, timestamp -- so "Küresel doluluk oranı
# 83,4" read as a measurement taken at the timestamp beside it, which is the
# single most misleading thing this API does.
#
# PUBLISHED_ESTIMATE_KEYS is the discriminator, imported from the service that
# writes those rows rather than re-listed here: it is exactly the set of
# metrics whose value is a transcribed IATA figure (app/services/kpi_service.py
# -> latest_published_estimates), so it cannot fall out of step with what the
# seed actually publishes.
#
# The YEAR comes from the row's own `as_of`, which is the same rule Kokpit's
# annual chart groups by (app/api/v1/kokpit.py get_annual_series): the seed
# dates a closed year to its 31 December and the open one to the report's
# publication date, so `as_of.year` is the period in both cases. And the KIND
# comes from `year_kind`, the seed's own helper -- so a KPI card and the chart
# beside it can never disagree about whether 2026 is a forecast.
#
# Its NAME comes from PERIOD_KIND_LABELS_TR in app/taxonomy.py, for the same
# reason one step further: this module used to keep its own Turkish words
# ("ön gerçekleşme") while Kokpit's outlook tile called the identical row
# "tahmini gerçekleşme". Agreeing on the kind and disagreeing on its name is
# still two answers to one question. The frontend reads that same map out of
# taxonomy.gen.ts.
# ---------------------------------------------------------------------------

#: What a live metric's value describes. Not "anlık": flights_today is derived
#: from an instantaneous count and fuel_price from a published assumption, and
#: neither is happening right now. "The last time we read it" is true of all of
#: them.
LIVE_PERIOD_LABEL_TR = "son ölçüm"


def period_label_for(metric_key: str, as_of: datetime) -> str:
    """"2026 · tahmin" for a published annual figure, "son ölçüm" otherwise."""
    if metric_key not in PUBLISHED_ESTIMATE_KEYS:
        return LIVE_PERIOD_LABEL_TR
    year = as_of.year
    return f"{year} · {PERIOD_KIND_LABELS_TR[year_kind(year)]}"


def deltas_for(new_value: float, old_value: float | None, unit: str) -> tuple[
    float | None, float | None
]:
    """(delta_pct, delta_points) between two readings of one metric.

    Exactly one of the pair is ever a number -- see the note above KpiOut in
    app/schemas/kpi.py. A metric already denominated in points reports the
    point difference; everything else reports the percent one.

    `None, None` when the comparison cannot be made: a missing previous
    reading, or a zero one, which cannot anchor a percent change. Zero would
    have said "unchanged", which is a measurement nobody took.
    """
    if old_value is None:
        return None, None
    if unit == "%":
        return None, round(new_value - old_value, 2)
    if not old_value:
        return None, None
    return round((new_value - old_value) / old_value * 100, 2), None

@router.get("", response_model=list[KpiOut])
async def list_kpis(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[KpiOut]:
    public_cache(response, AGGREGATES)
    repo = KpiRepository(db)
    out: list[KpiOut] = []

    # Three queries for the whole dashboard. This used to be a per-metric loop:
    # 16 trend queries + 14 last-year lookups + up to two live Yahoo calls,
    # ~30 sequential round trips against a pooled Neon endpoint, which measured
    # ~10s on production.
    metric_keys = list(KPI_DISPLAY)
    trends = await repo.trends_for(metric_keys, points=12)
    stored_ly = await repo.values_for_year(
        [k for k in metric_keys if k not in YAHOO_HISTORY_SYMBOLS], LY_YEAR
    )
    # Market LY prices are written by the KPI cron under "<metric>_ly"
    # (app/services/kpi_service.py) precisely so no request touches Yahoo.
    market_ly = await repo.latest_values(
        [f"{k}{LY_SUFFIX}" for k in metric_keys if k in YAHOO_HISTORY_SYMBOLS]
    )

    for metric_key, (label, up_is_good) in KPI_DISPLAY.items():
        history = trends.get(metric_key) or []
        if not history:
            continue

        latest = history[-1]
        # One rule for both comparisons, and the same one the detail page
        # applies: a load factor's movement is points on the dashboard card and
        # points on its detail page, or the two surfaces state different
        # numbers for the same move.
        delta_pct, delta_points = deltas_for(
            latest.value, history[-2].value if len(history) >= 2 else None, latest.unit
        )

        ly_value = (
            market_ly.get(f"{metric_key}{LY_SUFFIX}")
            if metric_key in YAHOO_HISTORY_SYMBOLS
            else stored_ly.get(metric_key)
        )
        ly_delta_pct, ly_delta_points = deltas_for(latest.value, ly_value, latest.unit)

        out.append(
            KpiOut(
                metric_key=metric_key,
                label=label,
                value=latest.value,
                unit=latest.unit,
                delta_pct=delta_pct,
                delta_points=delta_points,
                up_is_good=up_is_good,
                trend=[h.value for h in history],
                is_estimate=latest.is_estimate,
                as_of=latest.as_of,
                ly_value=ly_value,
                ly_delta_pct=ly_delta_pct,
                ly_delta_points=ly_delta_points,
                comparison_label=(
                    LY_COMPARISON_LABEL if ly_value is not None else PREVIOUS_COMPARISON_LABEL
                ),
                period_label=period_label_for(metric_key, latest.as_of),
            )
        )

    return out


# NOTE: registered before GET /{metric_key}. FastAPI would route the two-segment
# path correctly either way (a path param only matches one segment), but keeping
# the more specific route first makes the non-collision explicit.
@router.get("/{metric_key}/observations.csv")
async def export_kpi_observations_csv(
    metric_key: str, db: AsyncSession = Depends(get_db)
) -> Response:
    """Full stored history for one metric as a CSV download."""
    rows = await KpiRepository(db).all_observations(metric_key)
    if not rows:
        raise HTTPException(status_code=404, detail="No observations recorded yet for this KPI")

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["date", "value", "unit", "source", "source_url"])
    for row in rows:
        writer.writerow(
            [row.as_of.date().isoformat(), row.value, row.unit, row.source, row.source_url or ""]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="aerointel-kpi-{metric_key}.csv"'
        },
    )


# ---------------------------------------------------------------------------
# CROSS-VALIDATION: WHEN TWO READINGS ARE THE SAME NUMBER, AND WHEN THEY ARE
# NOT COMPARABLE AT ALL
#
# The detail page carries a "Çapraz doğrulama" block: our primary reading of a
# metric next to a second, unrelated source's (Yahoo's last trade vs the ECB
# reference fixing, via Frankfurter). It made two claims it had not earned:
#
#  * It never compared the two TIMESTAMPS. A Frankfurter row that stopped
#    updating three days ago sat beside today's Yahoo quote and, if the rate
#    happened not to have moved much, was badged "Eşleşiyor" -- corroboration
#    asserted between a reading and a stale one.
#  * A comparison it could not compute became 0.0 (`if latest.value else 0.0`),
#    and 0.0 is the strongest possible agreement. The one case where we knew
#    nothing rendered as the case where we were surest.
#
# Both are now expressible: `diff_pct` is Optional and `verdict` carries the
# answer, including "incomparable". The threshold moved here from the browser
# at the same time -- see CORROBORATION_MATCH_PCT.
# ---------------------------------------------------------------------------

#: Below this percent difference, two independent readings are the same number.
#: Half a percent is about the width of the spread between a live last-trade
#: quote and a daily reference fixing for the same pair -- i.e. the gap two
#: honest sources produce by measuring at different instants, not a
#: disagreement about the rate.
#:
#: It lived in kpi-detail-client.tsx as a bare `c.diff_pct < 0.5`, which put
#: the verdict in the layer that draws it: any second surface reading the same
#: payload was free to pick a different number and call the same pair matched
#: or not. It is a claim about our data, so it is decided on this side of the
#: wire, once.
CORROBORATION_MATCH_PCT = 0.5

#: How far apart the two readings may be timestamped and still be a
#: cross-check.
#:
#: The KPI refresh targets every 15 minutes and writes the primary and its
#: corroboration in the same run, so a healthy pair is timestamped seconds
#: apart. Two hours is eight missed ticks -- comfortably past scheduler jitter
#: (the cron is best-effort on a free runner, see .github/workflows/
#: jobs-kpis.yml) and unambiguously a cross-check source that has stopped
#: answering. Beyond it the two numbers describe different moments, and the
#: honest verdict is that they cannot be compared rather than that they agree.
CORROBORATION_MAX_AGE_GAP = timedelta(hours=2)

REASON_NO_PRIMARY_VALUE = "no_primary_value"
REASON_AS_OF_TOO_FAR_APART = "as_of_too_far_apart"


def corroboration_out(latest, other) -> KpiCorroborationOut:
    """One cross-check row, with its verdict already decided.

    `latest` is the primary observation; `other` is the second source's. The
    percent difference is measured against the primary because the primary is
    what the page is showing -- "this number, checked" rather than a symmetric
    distance between two equals.
    """
    common = {
        "source": other.source,
        "source_url": other.source_url,
        "value": other.value,
        "as_of": other.as_of,
    }

    def incomparable(reason: str) -> KpiCorroborationOut:
        return KpiCorroborationOut(
            diff_pct=None,
            verdict=CORROBORATION_INCOMPARABLE,
            verdict_label_tr=CORROBORATION_VERDICT_LABELS_TR[CORROBORATION_INCOMPARABLE],
            incomparable_reason=reason,
            **common,
        )

    if not latest.value:
        # A zero (or absent) primary cannot anchor a percent difference. This
        # is the branch that used to fall through to 0.0.
        return incomparable(REASON_NO_PRIMARY_VALUE)
    if abs(latest.as_of - other.as_of) > CORROBORATION_MAX_AGE_GAP:
        return incomparable(REASON_AS_OF_TOO_FAR_APART)

    diff_pct = round(abs(latest.value - other.value) / latest.value * 100, 3)
    verdict = CORROBORATION_MATCH if diff_pct < CORROBORATION_MATCH_PCT else CORROBORATION_DIVERGES
    return KpiCorroborationOut(
        diff_pct=diff_pct,
        verdict=verdict,
        verdict_label_tr=CORROBORATION_VERDICT_LABELS_TR[verdict],
        incomparable_reason=None,
        **common,
    )


@router.get("/{metric_key}", response_model=KpiDetailOut)
async def get_kpi_detail(
    metric_key: str,
    period: str = Query("1m", pattern="^(1w|1m|3m|6m|1y)$"),
    db: AsyncSession = Depends(get_db),
) -> KpiDetailOut:
    if metric_key not in KPI_DISPLAY:
        raise HTTPException(status_code=404, detail="Unknown KPI")

    repo = KpiRepository(db)
    label, up_is_good = KPI_DISPLAY[metric_key]

    latest_rows = await repo.trend(metric_key, points=2)
    if not latest_rows:
        raise HTTPException(status_code=404, detail="No observations recorded yet for this KPI")

    latest = latest_rows[-1]
    previous = latest_rows[0] if len(latest_rows) == 2 else None
    delta_pct, delta_points = deltas_for(
        latest.value, previous.value if previous else None, latest.unit
    )

    corroborations = [
        corroboration_out(latest, c) for c in await repo.latest_corroborations(metric_key)
    ]

    history, history_provenance = await _load_history(db, metric_key, period)

    return KpiDetailOut(
        metric_key=metric_key,
        label=label,
        value=latest.value,
        unit=latest.unit,
        delta_pct=delta_pct,
        delta_points=delta_points,
        up_is_good=up_is_good,
        is_estimate=latest.is_estimate,
        as_of=latest.as_of,
        period_label=period_label_for(metric_key, latest.as_of),
        comparison_label=comparison_label_for(metric_key, latest, previous),
        source=latest.source,
        source_url=latest.source_url,
        corroborations=corroborations,
        corroboration_match_pct=CORROBORATION_MATCH_PCT,
        history=history,
        history_is_external=history_provenance != OWN_HISTORY,
        history_provenance=history_provenance,
        history_provenance_tr=HISTORY_PROVENANCE_NOTES_TR[history_provenance],
        period=period,
    )


def comparison_label_for(metric_key: str, latest, previous) -> str | None:
    """What the delta on this page is measured against, said in Turkish.

    The browser hardcoded "önceki ölçüme göre" under every KPI's delta. For a
    live market metric that is exactly right -- the previous row is the
    previous quarter-hour's quote. For an annual published figure it is not:
    the stored rows ARE the yearly series, so the previous row is LAST YEAR,
    and the page was labelling a year-on-year change as a tick-to-tick one.

    None when there is nothing to compare against, so a surface renders no
    label rather than one describing a delta that does not exist.
    """
    if previous is None:
        return None
    if metric_key in PUBLISHED_ESTIMATE_KEYS and previous.as_of.year != latest.as_of.year:
        return f"{previous.as_of.year}'e göre"
    return PREVIOUS_COMPARISON_LABEL


# ---------------------------------------------------------------------------
# WHERE A CHART'S HISTORY CAME FROM -- THREE ANSWERS, NOT TWO
#
# `history_is_external` was a boolean, and the page printed "doğrudan kaynağın
# kendi arşivinden alınmıştır" whenever it was True. That sentence is true of
# Brent and of every FX pair. It is NOT true of /kpi/fuel_price, the one metric
# that has no archive of its own: its chart is Brent's published closes with
# JET_FUEL_CRACK_SPREAD_USD added to every point (see _load_history). Nobody
# publishes that series; we compute it. Presenting it as "the source's own
# archive" claims a jet-fuel price history that does not exist anywhere, which
# is the same class of error as showing a derived number without its
# derivation -- except here the derivation was not merely omitted, it was
# actively denied.
#
# So the field is a three-state slug and the sentence travels with it, written
# where the arithmetic is known instead of reassembled in the browser.
# ---------------------------------------------------------------------------

#: The metric's own published archive, fetched from the source under its own
#: symbol. Nothing was transformed.
SOURCE_ARCHIVE = "source_archive"
#: A REAL external archive belonging to a DIFFERENT instrument, transformed by
#: a stated rule to stand in for this metric. Externally sourced and derived,
#: which is neither of the other two answers.
DERIVED_EXTERNAL = "derived_external"
#: Our own accumulated observations, sparse until the scheduler has run a while.
OWN_HISTORY = "own_history"

HISTORY_PROVENANCE_NOTES_TR: dict[str, str] = {
    SOURCE_ARCHIVE: "Geçmiş veriler doğrudan kaynağın kendi arşivinden alınmıştır.",
    # Built from the constant rather than restating "57", so the sentence and
    # the arithmetic cannot drift apart the way this branch's crack spread
    # already did once (see _load_history).
    DERIVED_EXTERNAL: (
        f"Geçmiş veriler türetilmiştir: her nokta, Brent'in kendi yayımlanmış "
        f"kapanışına {JET_FUEL_CRACK_SPREAD_USD:.0f}$ crack spread "
        f"(IATA Haziran 2026 varsayımı) eklenerek hesaplanmıştır. Jet yakıtının "
        f"kendi işlem geçmişi değildir."
    ),
    OWN_HISTORY: (
        "Geçmiş veriler kendi periyodik ölçümlerimizden biriktirilmiştir -- "
        "zamanlayıcı çalıştıkça zamanla dolar, geriye dönük doldurulmaz."
    ),
}


async def _load_history(
    db: AsyncSession, metric_key: str, period: str
) -> tuple[list[KpiHistoryPointOut], str]:
    settings = get_settings()

    # fuel_price is derived from Brent crude (see kpi_service.py) -- reuse
    # oil's real historical closes and apply the same derivation, rather than
    # waiting months for our own scheduler to accumulate a derived history.
    #
    # That derivation is ADDITIVE: Brent plus IATA's published crack spread.
    # This branch was still applying an older 1.18x rule of thumb long after
    # kpi_service.py moved the live value onto JET_FUEL_CRACK_SPREAD_USD, so
    # the jet-fuel detail page drew a history that ended ~40% below the current
    # value printed above it -- a visible cliff between the last historical
    # point and today's reading. The constant is imported from the service that
    # writes the value so the two can no longer drift apart.
    yahoo_symbol = YAHOO_HISTORY_SYMBOLS.get(metric_key)
    crack_spread = 0.0
    provenance = SOURCE_ARCHIVE
    if metric_key == "fuel_price":
        yahoo_symbol = YAHOO_HISTORY_SYMBOLS["oil_price"]
        crack_spread = JET_FUEL_CRACK_SPREAD_USD
        # Brent's real archive, plus a stated constant -- a third kind of
        # provenance, and the reason this is a slug and not a boolean.
        provenance = DERIVED_EXTERNAL

    if yahoo_symbol:
        points = await fetch_history(settings.yahoo_finance_base_url, yahoo_symbol, period)
        if points:
            return (
                [KpiHistoryPointOut(as_of=ts, value=round(v + crack_spread, 2)) for ts, v in points],
                provenance,
            )
        # Yahoo Finance unreachable -- fall through to our own accumulated
        # history rather than returning nothing. The provenance falls with it:
        # what is drawn is now our own observations, whatever we would have
        # drawn had the fetch succeeded.

    since = datetime.now(timezone.utc) - PERIOD_TO_TIMEDELTA[period]
    repo = KpiRepository(db)
    rows = await repo.history_since(metric_key, since)
    return [KpiHistoryPointOut(as_of=r.as_of, value=r.value) for r in rows], OWN_HISTORY
