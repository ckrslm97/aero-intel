"""Kokpit's "Sinyal Panosu": four status tiles, each driven by one real number.

WHY THIS IS NOT A SCORE
-----------------------
The obvious design for the top of an executive dashboard is a single 0-100
"health score". It was rejected on purpose. Blending an FX move, a Brent
percentile, a count of clustered disaster reports and a count of rival press
releases into one number requires weights nobody can defend, and the result
looks precise while meaning nothing -- the exact failure mode the rest of this
codebase (curated_seed.py's no-averaging rule, historical_seed.py's "nothing is
estimated, interpolated or invented") exists to avoid.

So: four tiles, four drivers, four stated thresholds. Every tile prints the
number it banded, the band it fell into, and how the band was decided. A reader
who disagrees with a threshold can see it and discount it; a reader of a
composite score cannot.

WHY THE LEVELS ARE COMPUTED HERE AND NOT IN THE BROWSER
-------------------------------------------------------
The same level appears twice on the page: the Sinyal Panosu tile, and the
"Yakıt & Enerji" panel's chip. Two client-side derivations of one threshold are
two chances to disagree -- the same argument risks.py makes for scoring
countries server-side. One endpoint, one answer, and the threshold tables below
are data, so a test asserts every band boundary directly rather than
re-implementing the comparison.

Nothing here calls an LLM. Every value is arithmetic over rows this app already
stores, plus Brent's own published history from Yahoo.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.promotions import new_promotion_counts

# Both of these are the rollup that already backs a page, reused rather than
# re-derived: a cheaper second query would eventually state a number the page
# it links to cannot reproduce. See each function's own docstring.
from app.api.v1.risks import UNKNOWN_COUNTRY, RiskRadarOut, aggregate_risks
from app.core.config import get_settings
from app.core.logging import get_logger
from app.ingest.markets import fetch_history
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kokpit import CockpitSignalOut
from app.services.insights_service import airline_momentum
from app.taxonomy import RIVAL_CODES

logger = get_logger(__name__)

# --- Levels ---------------------------------------------------------------

GOOD = "good"
WARNING = "warning"
CRITICAL = "critical"
#: Not a band: the driver could not be read at all. Kept distinct from `good`
#: so a missing feed never renders as a green "all clear".
UNKNOWN = "unknown"

#: The tile's word for each level. "Sakin" rather than "İyi", because none of
#: these four drivers is a thing that can be *good* -- a currency that has not
#: moved is calm, not healthy.
LEVEL_LABELS_TR: dict[str, str] = {
    GOOD: "Sakin",
    WARNING: "Dikkat",
    CRITICAL: "Yüksek",
    UNKNOWN: "Veri yok",
}

#: Worst-wins ordering, for the one tile whose level is the worse of two bands.
_LEVEL_RANK = {GOOD: 0, WARNING: 1, CRITICAL: 2}


@dataclass(frozen=True)
class Band:
    """One row of a threshold table: a value strictly below `upper` (and at or
    above the previous row's `upper`) gets `level`. The final row must carry
    `upper=None` -- "everything above" -- which test_cockpit_signals.py asserts
    for every table here rather than trusting."""

    upper: float | None
    level: str


def band_for(value: float, table: tuple[Band, ...]) -> str:
    """The first band whose `upper` the value falls under. Tables are written
    low to high, so reading one top to bottom is the sentence `method_tr`
    prints for it."""
    for band in table:
        if band.upper is None or value < band.upper:
            return band.level
    raise ValueError("threshold table has no open-ended final band")


def worst(*levels: str) -> str:
    return max(levels, key=lambda level: _LEVEL_RANK[level])


# --- Threshold tables -----------------------------------------------------

#: Kur Riski, banded on the ABSOLUTE 30-day move: a currency pair moving is
#: neither good nor bad on its own (the same convention fx-board.tsx renders
#: its deltas with), so what is banded is how far it moved, not which way.
FX_30D_ABS_MOVE_BANDS: tuple[Band, ...] = (
    Band(2.0, GOOD),
    Band(5.0, WARNING),
    Band(None, CRITICAL),
)

#: Yakıt Riski, part one: where today's Brent sits inside its own last 12
#: months, 0-100. A high percentile is a high cost base, which is a risk to an
#: airline in a way a high USD/TRY is not automatically one.
FUEL_PERCENTILE_BANDS: tuple[Band, ...] = (
    Band(50.0, GOOD),
    Band(80.0, WARNING),
    Band(None, CRITICAL),
)

#: Yakıt Riski, part two: the SIGNED 30-day move. A fall in the cost base is
#: not a cost risk, so only rises escalate -- deliberately unlike the FX table.
FUEL_30D_RISE_BANDS: tuple[Band, ...] = (
    Band(2.0, GOOD),
    Band(8.0, WARNING),
    Band(None, CRITICAL),
)

#: Risk Radarı: how many HIGH-severity signals the radar is currently holding.
RISK_HIGH_COUNT_BANDS: tuple[Band, ...] = (
    Band(1, GOOD),
    Band(3, WARNING),
    Band(None, CRITICAL),
)

#: Rakip Aktivitesi: campaigns first seen in the last 48 hours. This is a
#: NEWS/CAMPAIGN VOLUME band and nothing else -- there is no rival capacity,
#: load factor or market share data anywhere in this system, and the tile's
#: own method note says so in as many words.
COMPETITOR_48H_COUNT_BANDS: tuple[Band, ...] = (
    Band(3, GOOD),
    Band(6, WARNING),
    Band(None, CRITICAL),
)

#: Matches risk-radar-client.tsx's own DAYS, so the tile's count and the page
#: it links to cover the same window.
RISK_WINDOW_DAYS = 14
#: How far back airline_momentum compares (7 days vs the 7 before it).
MOMENTUM_WINDOW_DAYS = 7


# --- Turkish number formatting -------------------------------------------
# Formatted here rather than in the browser so a tile's headline number and the
# sentence under it are literally the same string, rounded once.


def tr_number(value: float, decimals: int = 2) -> str:
    """1234.5 -> "1.234,50" -- Turkish thousands/decimal separators."""
    grouped = f"{value:,.{decimals}f}"
    return grouped.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def tr_percent(value: float, decimals: int = 1) -> str:
    return f"%{tr_number(abs(value), decimals)}"


def tr_signed_percent(value: float, decimals: int = 1) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    return f"{sign}%{tr_number(abs(value), decimals)}"


def percentile_of(value: float, series: list[float]) -> float | None:
    """Share of `series` at or below `value`, 0-100. None for an empty series:
    an honest "could not place it", never a defaulted 50."""
    if not series:
        return None
    at_or_below = sum(1 for point in series if point <= value)
    return round(at_or_below / len(series) * 100, 1)


# --- Tile builders (pure) -------------------------------------------------
# Each takes already-fetched numbers and returns the finished tile. Free of
# I/O, so every band boundary is directly unit-testable.

FX_METHOD_TR = (
    "USD/TRY'nin son 30 günlük mutlak değişimi bantlanır: %2 altı sakin, "
    "%2-%5 dikkat, %5 üzeri yüksek. Yön değil, hareketin büyüklüğü ölçülür."
)

FUEL_METHOD_TR = (
    "Brent'in son 12 aylık kendi aralığındaki yüzdelik dilimi (%50 altı sakin, "
    "%80 altı dikkat, üstü yüksek) ile 30 günlük ARTIŞI (%2 altı sakin, %8 altı "
    "dikkat, üstü yüksek) ayrı ayrı bantlanır; kötü olan kazanır. Düşüş maliyet "
    "riskini artırmadığı için bandı yükseltmez."
)


def build_fx_signal(
    *,
    spot: float | None,
    move_30d_pct: float | None,
    forecast_values: list[float],
    as_of: datetime | None = None,
    source: str | None = None,
    source_url: str | None = None,
) -> CockpitSignalOut:
    common = {
        "key": "fx",
        "label_tr": "Kur Riski",
        "method_tr": FX_METHOD_TR,
        "source": source or "Yahoo Finance",
        "source_url": source_url,
        "href": "/kpi/fx_usd_try",
        "as_of": as_of,
    }

    if spot is None or move_30d_pct is None:
        return CockpitSignalOut(
            level=UNKNOWN,
            level_label_tr=LEVEL_LABELS_TR[UNKNOWN],
            value_label="—",
            reason_tr="USD/TRY için 30 günlük karşılaştırmaya yetecek geçmiş henüz yok.",
            **common,
        )

    reason = f"USD/TRY {tr_number(spot, 2)} · 30 günde {tr_signed_percent(move_30d_pct)}."

    # The curated bank forecasts as a RANGE, never a consensus number:
    # averaging them is forbidden by the module that curates them (see
    # app/ingest/curated_seed.py). The two endpoints of the range are two
    # institutions' own published figures, each still individually attributed
    # in the forecast table further down the page.
    if forecast_values:
        low, high = min(forecast_values), max(forecast_values)
        gap_low = (low - spot) / spot * 100
        gap_high = (high - spot) / spot * 100
        reason += (
            f" Küratörlü banka tahminleri {tr_number(low, 2)}–{tr_number(high, 2)} aralığında"
            f" ({tr_signed_percent(gap_low, 0)}…{tr_signed_percent(gap_high, 0)})."
        )

    level = band_for(abs(move_30d_pct), FX_30D_ABS_MOVE_BANDS)
    return CockpitSignalOut(
        level=level,
        level_label_tr=LEVEL_LABELS_TR[level],
        value_label=tr_signed_percent(move_30d_pct),
        reason_tr=reason,
        **common,
    )


def build_fuel_signal(
    *,
    brent: float | None,
    percentile: float | None,
    move_30d_pct: float | None,
    as_of: datetime | None = None,
    source: str | None = None,
    source_url: str | None = None,
) -> CockpitSignalOut:
    common = {
        "key": "fuel",
        "label_tr": "Yakıt Riski",
        "method_tr": FUEL_METHOD_TR,
        "source": source or "Yahoo Finance (BZ=F)",
        "source_url": source_url,
        "href": "/kpi/oil_price",
        "as_of": as_of,
    }

    levels: list[str] = []
    if percentile is not None:
        levels.append(band_for(percentile, FUEL_PERCENTILE_BANDS))
    if move_30d_pct is not None:
        levels.append(band_for(move_30d_pct, FUEL_30D_RISE_BANDS))

    if brent is None or not levels:
        return CockpitSignalOut(
            level=UNKNOWN,
            level_label_tr=LEVEL_LABELS_TR[UNKNOWN],
            value_label=f"{tr_number(brent, 2)} $" if brent is not None else "—",
            reason_tr=(
                "Brent için bantlamaya yetecek geçmiş henüz yok."
                if brent is not None
                else "Brent için henüz kayıtlı bir fiyat yok."
            ),
            **common,
        )

    parts = [f"Brent {tr_number(brent, 2)} $/varil"]
    if percentile is not None:
        parts.append(f"son 1 yılın {tr_percent(percentile, 0)}'lik diliminde")
    if move_30d_pct is not None:
        parts.append(f"30 günde {tr_signed_percent(move_30d_pct)}")

    # Said out loud on every fuel tile: this is the world price of crude, not
    # a carrier's hedged fuel bill, which this system has no data for at all.
    #
    # The derived jet-fuel number deliberately does NOT appear here. It is
    # already on this page twice -- in the market strip and in the "Yakıt &
    # Enerji" panel -- both times with its derivation printed beside it, and a
    # third copy made this tile twice the height of its three neighbours for a
    # number the reader had already met.
    reason = " · ".join(parts) + ". Küresel Brent hareketi; şirket yakıt maliyeti değil."

    level = worst(*levels)
    return CockpitSignalOut(
        level=level,
        level_label_tr=LEVEL_LABELS_TR[level],
        value_label=f"{tr_number(brent, 2)} $",
        reason_tr=reason,
        **common,
    )


def build_risk_signal(
    *,
    high_count: int,
    total: int,
    top_country: str | None = None,
    top_country_high: int = 0,
    days: int = RISK_WINDOW_DAYS,
) -> CockpitSignalOut:
    level = band_for(high_count, RISK_HIGH_COUNT_BANDS)
    reason = f"Son {days} günde {total} sinyal, {high_count} tanesi yüksek şiddetli."
    if top_country:
        suffix = f" ({top_country_high} yüksek)." if top_country_high else "."
        reason += f" En yoğun ülke: {top_country}{suffix}"

    return CockpitSignalOut(
        key="risk",
        label_tr="Risk Radarı",
        level=level,
        level_label_tr=LEVEL_LABELS_TR[level],
        value_label=str(high_count),
        reason_tr=reason,
        method_tr=(
            f"Son {days} günün haber akışından sınıflandırılan risk sinyalleri "
            "kümelenerek sayılır (aynı olayı yazan üç kaynak tek sinyaldir). "
            "Yüksek şiddetli sinyal sayısı: 0 sakin, 1-2 dikkat, 3+ yüksek."
        ),
        source="AeroIntel risk sınıflandırması (haber akışı)",
        source_url=None,
        href="/risk-radari",
        as_of=None,
    )


def build_competitor_signal(
    *,
    new_count: int,
    airline_codes: list[str],
    window_hours: int,
    top_mover_name: str | None = None,
    top_mover_delta: int | None = None,
) -> CockpitSignalOut:
    level = band_for(new_count, COMPETITOR_48H_COUNT_BANDS)
    reason = f"Son {window_hours} saatte {new_count} yeni kampanya"
    if airline_codes:
        reason += f" ({', '.join(airline_codes)})"
    reason += "."
    if top_mover_name and top_mover_delta:
        direction = "artış" if top_mover_delta > 0 else "azalış"
        reason += (
            f" Haber hacminde en çok hareket eden rakip: {top_mover_name} "
            f"({top_mover_delta:+d} {direction}, son {MOMENTUM_WINDOW_DAYS} gün / "
            f"önceki {MOMENTUM_WINDOW_DAYS} gün)."
        )

    return CockpitSignalOut(
        key="competitor",
        label_tr="Rakip Aktivitesi",
        level=level,
        level_label_tr=LEVEL_LABELS_TR[level],
        value_label=str(new_count),
        reason_tr=reason,
        method_tr=(
            f"Son {window_hours} saatte ilk kez görülen rakip kampanya sayısı "
            "bantlanır: 0-2 sakin, 3-5 dikkat, 6+ yüksek. Bu bir HABER/KAMPANYA "
            "HACMİ ölçüsüdür — kapasite, doluluk veya pazar payı verisi değildir "
            "ve öyle okunamaz."
        ),
        source="AeroIntel kampanya tespiti + haber akışı",
        source_url=None,
        href="/kampanyalar",
        as_of=None,
    )


# --- Orchestration (I/O) --------------------------------------------------


async def cockpit_signals(
    db: AsyncSession, *, radar: RiskRadarOut | None = None
) -> list[CockpitSignalOut]:
    """Fetch each tile's driver and band it. Returned in display order.

    `radar` is an escape hatch for a caller that has already run
    `aggregate_risks` for its own reasons -- the Sinyaller aggregate
    (app/services/signals_service.py) renders both these tiles and the radar's
    own high-severity signals in one response, and re-clustering a 14-day
    window twice per request buys nothing. Passing it in is also what
    guarantees the tile's count and the signals listed beside it come from the
    same rollup rather than from two runs that could differ. Production's own
    /kokpit/signals passes nothing and fetches it here, exactly as before.
    """
    settings = get_settings()
    kpis = KpiRepository(db)
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    async def move_30d(metric_key: str) -> tuple[object | None, float | None]:
        latest = await kpis.latest(metric_key)
        prior = await kpis.closest_before(metric_key, thirty_days_ago)
        if latest is None or prior is None or not prior.value:
            return latest, None
        return latest, round((latest.value - prior.value) / prior.value * 100, 2)

    usd_try, fx_move = await move_30d("fx_usd_try")
    brent, brent_move = await move_30d("oil_price")
    forecasts = await CuratedRepository(db).fx_forecasts(currency_pair="USD/TRY")

    # Brent's own published year, from the same Yahoo path the KPI detail page
    # already uses on the request path. fetch_history never raises -- it
    # returns [] on any failure -- so a provider outage degrades this tile to
    # "30-day move only" instead of failing the whole board.
    percentile = None
    if brent is not None:
        history = await fetch_history(settings.yahoo_finance_base_url, "BZ=F", "1y")
        percentile = percentile_of(brent.value, [value for _, value in history])
    if radar is None:
        radar = await aggregate_risks(db, days=RISK_WINDOW_DAYS)
    high_count = sum(country.severity_counts.high for country in radar.countries)
    # countries[] is already sorted worst-first. The unplaced bucket is skipped:
    # "Belirtilmemiş" is a data-quality residue, not a country to name as the
    # hot spot (risks.py sorts it last for the same reason).
    top_country = next(
        (c for c in radar.countries if c.country != UNKNOWN_COUNTRY), None
    )

    new_campaigns = await new_promotion_counts(db)

    # Rivals only. airline_momentum ranks every carrier the news mentions,
    # including the home carrier, and a tile headed "Rakip Aktivitesi" naming
    # THY as its top mover would be plainly wrong.
    movers = [
        mover
        for mover in await airline_momentum(db, window_days=MOMENTUM_WINDOW_DAYS, limit=20)
        if mover["code"] in RIVAL_CODES
    ]
    top_mover = movers[0] if movers else None

    return [
        build_fx_signal(
            spot=usd_try.value if usd_try else None,
            move_30d_pct=fx_move,
            forecast_values=[row.value for row in forecasts],
            as_of=usd_try.as_of if usd_try else None,
            source=usd_try.source if usd_try else None,
            source_url=usd_try.source_url if usd_try else None,
        ),
        build_fuel_signal(
            brent=brent.value if brent else None,
            percentile=percentile,
            move_30d_pct=brent_move,
            as_of=brent.as_of if brent else None,
            source=brent.source if brent else None,
            source_url=brent.source_url if brent else None,
        ),
        build_risk_signal(
            high_count=high_count,
            total=radar.total,
            top_country=top_country.country if top_country else None,
            top_country_high=top_country.severity_counts.high if top_country else 0,
        ),
        build_competitor_signal(
            new_count=new_campaigns["count"],
            airline_codes=new_campaigns["airline_codes"],
            window_hours=new_campaigns["window_hours"],
            top_mover_name=top_mover["name"] if top_mover else None,
            top_mover_delta=top_mover["delta"] if top_mover else None,
        ),
    ]
