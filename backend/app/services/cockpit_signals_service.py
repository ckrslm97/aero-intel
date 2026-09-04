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
stores, plus Brent's own published history from Yahoo -- and the fuel tile takes
ALL of its Brent numbers from `energy_service.brent_indicators()`, the same one
series the "Yakıt & Enerji" panel prints, so the two cannot state different
prices, moves or percentiles for one contract on one page.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.promotions import new_promotion_counts

# Both of these are the rollup that already backs a page, reused rather than
# re-derived: a cheaper second query would eventually state a number the page
# it links to cannot reproduce. See each function's own docstring.
from app.api.v1.risks import (
    DEFAULT_WINDOW_DAYS,
    UNKNOWN_COUNTRY,
    RiskRadarOut,
    aggregate_risks,
)
from app.core.logging import get_logger
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.schemas.kokpit import CockpitSignalOut
from app.services.energy_service import BRENT_SYMBOL, brent_indicators
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

#: Risk Radarı: how many HIGH-severity signals the radar is currently holding
#: OVER RISK_WINDOW_DAYS -- which is the radar's own default window, five days,
#: not the fourteen this table was first written against.
#:
#: Re-checked when the window was corrected, because a count band read over a
#: shorter window is a different question and the numbers do not carry over for
#: free. Two things make these three rows survive the change:
#:
#: * It is a COUNT of clustered high-severity signals, not a rate. Nothing in
#:   0/1-2/3+ is derived from the window length by arithmetic, so shortening the
#:   window does not leave a stale divisor behind.
#: * Shortening it can only move a tile DOWN a band, never up: the 5-day count
#:   is a subset of the 14-day one. The band therefore got stricter -- three
#:   high-severity signals now mean three inside five days, a genuinely dense
#:   week -- and a threshold erring towards "Sakin" is the safe direction for a
#:   tile nobody can audit at a glance.
#:
#: `method_tr` prints the window next to the band, so a reader who disagrees
#: with the thresholds can see which window they were applied over.
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

#: The radar's own default window, imported rather than restated.
#:
#: It used to be a hand-typed 14 sitting beside a comment claiming it matched
#: the page -- and it had not for as long as risks.DEFAULT_WINDOW_DAYS has been
#: 5. The tile counted a fortnight, the Risk Radarı the tile links to opened on
#: five days, and the two numbers disagreed by construction: clicking a tile
#: reading "4" landed on a page showing two signals. One name, one window, and
#: no second place to forget to change it.
RISK_WINDOW_DAYS = DEFAULT_WINDOW_DAYS
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


# --- Tile builders (pure) -------------------------------------------------
# Each takes already-fetched numbers and returns the finished tile. Free of
# I/O, so every band boundary is directly unit-testable.

FX_METHOD_TR = (
    "USD/TRY'nin son 30 günlük mutlak değişimi bantlanır: %2 altı sakin, "
    "%2-%5 dikkat, %5 üzeri yüksek. Yön değil, hareketin büyüklüğü ölçülür."
)

FUEL_METHOD_TR = (
    "Brent'in son 12 aylık GÜNLÜK KAPANIŞLARI içindeki yüzdelik dilimi (%50 altı "
    "sakin, %80 altı dikkat, üstü yüksek) ile aynı serideki 30 günlük ARTIŞI "
    "(%2 altı sakin, %8 altı dikkat, üstü yüksek) ayrı ayrı bantlanır; kötü olan "
    "kazanır. Düşüş maliyet riskini artırmadığı için bandı yükseltmez. Fiyat ve "
    "yüzdelerin tamamı bu tek yayımlanmış kapanış serisinden gelir — sayfadaki "
    "\"Yakıt & Enerji\" paneliyle aynı seri."
)


@dataclass(frozen=True)
class FxForecastPoint:
    """One curated bank forecast, reduced to what the tile is allowed to say
    about it: WHO said it, for WHEN, and the number.

    The horizon is not optional decoration. `build_fx_signal` used to take a
    bare `list[float]` and print min-max as "the range of bank forecasts" --
    and those floats were a 3-month call, a 12-month call and two year-end
    calls, mixed. The resulting "51,40–66,00" was not a range any institution
    or any date would recognise: its two ends were nine months apart. A type
    that cannot be constructed without a horizon and an institution is what
    stops that sentence being writable again.
    """

    institution: str
    #: The institution's own label -- "+3m", "end-2026". Never rewritten; see
    #: app/models/curated.py.
    horizon_label: str
    value: float


def build_fx_signal(
    *,
    spot: float | None,
    move_30d_pct: float | None,
    forecasts: list[FxForecastPoint],
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

    # The curated bank forecasts, NEVER a consensus number: averaging them is
    # forbidden by the module that curates them (see app/ingest/curated_seed.py).
    #
    # And never an unlabelled "range" either, which is what this was. The rows
    # reaching a USD/TRY tile are a Danske +3m, a Danske +12m, a JPMorgan
    # end-2026 and a Garanti year-end; min-max over them printed
    # "51,40–66,00 aralığında", an interval whose ends are nine months and two
    # institutions apart, presented as though four banks had bracketed one
    # number. A reader could only take it for a spread of opinion about the
    # same moment, which is the one thing it is not.
    #
    # Rows whose horizon has already elapsed never arrive here at all -- the
    # caller asks the repository for `only_upcoming` -- so nothing below can be
    # anchored to a date in the past.
    if forecasts:
        low = min(forecasts, key=lambda f: f.value)
        high = max(forecasts, key=lambda f: f.value)
        gap_low = tr_signed_percent((low.value - spot) / spot * 100, 0)
        gap_high = tr_signed_percent((high.value - spot) / spot * 100, 0)
        horizons = {f.horizon_label for f in forecasts}

        if len(forecasts) == 1:
            # One curated row. "Aralık" would be a range of one. Tested on the
            # list length and not on `low is high`, which is also true of two
            # institutions that happen to have published the same number.
            reason += (
                f" Küratörlü tek banka tahmini: {low.institution}, {low.horizon_label} vadeli"
                f" {tr_number(low.value, 2)} ({gap_low})."
            )
        elif len(horizons) == 1:
            # Same horizon on every row: a genuine spread of opinion about one
            # date, and the only case where "aralık" is the honest word.
            horizon = next(iter(horizons))
            reason += (
                f" Küratörlü banka tahminleri ({horizon} vadeli)"
                f" {tr_number(low.value, 2)}–{tr_number(high.value, 2)} aralığında"
                f" ({gap_low}…{gap_high})."
            )
        else:
            # Different horizons: two endpoints, each named with its own
            # institution and its own vade, and said out loud not to be a range.
            reason += (
                " Küratörlü banka tahminleri farklı vadeli:"
                f" en düşük {tr_number(low.value, 2)}"
                f" ({low.institution}, {low.horizon_label} vadeli, {gap_low}),"
                f" en yüksek {tr_number(high.value, 2)}"
                f" ({high.institution}, {high.horizon_label} vadeli, {gap_high})."
                " Tek bir aralık değil."
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
        # NO IN-APP DETAIL PAGE, deliberately -- `href` is None and the schema
        # documents that as "the tile has no deeper page".
        #
        # It used to link to /kpi/oil_price, and that was correct only while
        # this tile read `kpis.latest("oil_price")`: the same row the detail
        # page prints. It no longer does. Every number here now comes from the
        # PUBLISHED DAILY CLOSE (services/energy_service.brent_indicators), so
        # that the tile and the Market Pulse Brent cell read one series over
        # one period; /kpi/oil_price still prints the KPI archive, which is the
        # intraday `regularMarketPrice` our cron happened to catch
        # (services/kpi_service.py -> ingest/markets.fetch_quote). Mid-session
        # those are two different prices with two different `as_of`s.
        #
        # A link whose two ends print different numbers for the same contract,
        # under the same "Yahoo Finance (BZ=F)" label, is worse than no link:
        # it is the "one contract, two answers" error this whole change set
        # exists to remove, just relocated from tile<->panel to tile<->detail.
        # `source_url` still reaches the contract itself, and the same close --
        # with its day and week windows and its sparkline -- is on this page in
        # Market Pulse. Restore a link only to a surface fed by THIS series.
        "href": None,
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
    db: AsyncSession,
    *,
    radar: RiskRadarOut | None = None,
    momentum: list[dict] | None = None,
) -> list[CockpitSignalOut]:
    """Fetch each tile's driver and band it. Returned in display order.

    `radar` and `momentum` are escape hatches for a caller that has already run
    those two aggregates for its own reasons -- the Sinyaller aggregate
    (app/services/signals_service.py) renders both these tiles AND the radar's
    high-severity signals AND the rival movers in one response, and running
    either aggregate twice per request buys nothing.

    Passing them in is also what guarantees the tile's number and the cards
    listed beside it come from one computation rather than from two runs that
    could differ: two `airline_momentum` calls anchor their 7-vs-7 windows on
    two readings of the clock, so the tile could name a top mover the cards
    below it rank differently. `momentum` is the RAW ranking, unfiltered --
    this function keeps its own rivals-only rule, because "which carrier the
    tile may name" is a question about the tile.

    Production's own /kokpit/signals passes neither and fetches both here,
    exactly as before.
    """
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
    # only_upcoming: a bank's "+3m" published in March says nothing about where
    # the rate goes from here once June has passed, and an elapsed horizon was
    # free to be the endpoint the tile quoted. The rows stay in the table --
    # they are a true record of what was said -- they just stop steering a tile
    # about the road ahead.
    forecast_rows = await CuratedRepository(db).fx_forecasts(
        currency_pair="USD/TRY", only_upcoming=True
    )

    # EVERY Brent number on this tile comes from one call, and it is the same
    # call the "Yakıt & Enerji" panel makes three inches down the page
    # (services/energy_service.brent_indicators).
    #
    # It used to be three sources for one contract: the price was
    # `kpis.latest("oil_price")`, an intraday quote our cron happened to catch;
    # the 30-day move was computed over our archive of those quotes; and the
    # percentile placed that quote inside a WEEKLY year (~52 closes) while the
    # panel below placed the daily close inside a DAILY one (~250). Same
    # contract, same screen, two prices, two moves and two percentiles -- and
    # the reader had no way to tell which of them the level was banded from.
    #
    # `fetch_history` never raises, so an outage returns an empty series and
    # every field below is None: the tile degrades to UNKNOWN ("Veri yok")
    # together with the panel, rather than one of them printing a stored
    # number as if it were today's.
    brent = await brent_indicators()
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
    if momentum is None:
        momentum = await airline_momentum(
            db, window_days=MOMENTUM_WINDOW_DAYS, limit=20
        )
    movers = [mover for mover in momentum if mover["code"] in RIVAL_CODES]
    top_mover = movers[0] if movers else None

    return [
        build_fx_signal(
            spot=usd_try.value if usd_try else None,
            move_30d_pct=fx_move,
            forecasts=[
                FxForecastPoint(
                    institution=row.institution,
                    horizon_label=row.horizon_label,
                    value=row.value,
                )
                for row in forecast_rows
            ],
            as_of=usd_try.as_of if usd_try else None,
            source=usd_try.source if usd_try else None,
            source_url=usd_try.source_url if usd_try else None,
        ),
        build_fuel_signal(
            brent=brent.value,
            percentile=brent.percentile_1y,
            # The published series' own 30-day step, which is what the panel
            # prints as "1 aylık değişim". Both now move together or not at all.
            move_30d_pct=brent.month_change_pct,
            # The CLOSE's own timestamp -- when the number was true -- not when
            # our cron stored it.
            as_of=brent.as_of,
            source=f"Yahoo Finance ({BRENT_SYMBOL})",
            source_url=f"https://finance.yahoo.com/quote/{BRENT_SYMBOL}",
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
