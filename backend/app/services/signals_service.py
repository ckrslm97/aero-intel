"""SİNYALLER: one early-warning list composed from the streams this system
already has.

WHAT THIS IS AND IS NOT
-----------------------
Nothing here detects anything. Every row is produced by an existing surface --
Kokpit's four tiles, the campaign alert inbox, the Risk Radarı's clustered
rollup, BİZ's rival and strategic event queries, the Hub page's new-route
signals, İçgörüler' airline momentum -- and this module's whole job is to state
them in one shape so a reader can scan seven streams in one pass instead of
seven pages.

That constraint is what makes the page honest, and it is deliberately visible
in the code: every builder below takes an already-computed stream and maps it,
and none of them opens a query of its own. A stream that does not exist gets no
card -- there is no "fare change" or "interest rate" row here, because this
system ingests neither, and a placeholder that looked like one would be the
only untrue thing on the page.

THE FOUR KINDS
--------------
The owner's four filter buckets, and exactly which real streams reach each:

    kind         label              streams
    -----------  -----------------  ------------------------------------------
    market       Piyasa & Ağ        kokpit fx + fuel tiles, new-route signals
    risk         Risk               kokpit risk tile, high-severity risk
                                    signals from the same rollup
    competitor   Rakip              kokpit competitor tile, campaign alerts,
                                    rival event counts, airline momentum
    financial    Finans & Strateji  strategic developments (finance / fleet /
                                    sustainability / regulatory events)

SEVERITY IS CARRIED, NEVER INVENTED
-----------------------------------
Three of the seven streams publish a band of their own: a Kokpit tile's level, a
campaign alert's priority, a risk cluster's severity. Those are mapped through
the tables below and nothing else happens to them.

The other four -- rival event counts, strategic developments, new routes,
airline momentum -- have no severity anywhere in their data. They are mapped to
`low` and every one of their cards carries a `severity_basis_tr` saying so in
as many words. Banding them on a count would mean inventing a threshold here
and presenting it as if the stream had published it, which is the one thing
cockpit_signals_service.py's own docstring exists to refuse.
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaign_alerts import open_alerts
from app.api.v1.risks import RiskRadarOut, aggregate_risks
from app.models.campaign_alert import ALERT_TYPE_LABELS_TR
from app.schemas.signals import SignalOut, SignalsOut, SignalStreamOut
from app.services.biz_service import competitor_signals, strategic_developments
from app.services.cockpit_signals_service import (
    MOMENTUM_WINDOW_DAYS,
    RISK_WINDOW_DAYS,
    cockpit_signals,
)
from app.services.insights_service import airline_momentum
from app.services.network_signals_service import network_signals
from app.taxonomy import CATEGORY_LABELS_TR, RIVAL_CODES

# --- kinds ------------------------------------------------------------------

MARKET = "market"
RISK = "risk"
COMPETITOR = "competitor"
FINANCIAL = "financial"

KIND_LABELS_TR: dict[str, str] = {
    MARKET: "Piyasa & Ağ",
    RISK: "Risk",
    COMPETITOR: "Rakip",
    FINANCIAL: "Finans & Strateji",
}

#: Display order for the filter chips. Stated as data so a test asserts it
#: rather than re-deriving it from dict insertion order.
KIND_ORDER: tuple[str, ...] = (RISK, COMPETITOR, MARKET, FINANCIAL)

# --- severity ---------------------------------------------------------------

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"
#: Not a band: the driver could not be read at all. Kept distinct from `low`
#: for the same reason cockpit_signals_service.py keeps it distinct from
#: `good` -- a missing feed must never render as an all-clear.
UNKNOWN = "unknown"

SEVERITY_ORDER: tuple[str, ...] = (CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN)

SEVERITY_LABELS_TR: dict[str, str] = {
    CRITICAL: "Kritik",
    HIGH: "Yüksek",
    MEDIUM: "Orta",
    LOW: "Düşük",
    UNKNOWN: "Veri yok",
}

_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITY_ORDER)}

#: Kokpit tile level -> severity. A tile's "Yüksek" is a threshold band on a
#: rolling market driver, not an alert that fired, so it maps to `high` and
#: never to `critical`: `critical` is reserved for the campaign alert ladder,
#: whose CRITICAL means "a named rival just did something with a deadline".
#: Promoting a banded FX move above that would push the rows a desk actually
#: has to act on this morning off the top of the list.
COCKPIT_LEVEL_SEVERITY: dict[str, str] = {
    "critical": HIGH,
    "warning": MEDIUM,
    "good": LOW,
    "unknown": UNKNOWN,
}

#: Campaign alert priority -> severity. A straight relabelling: the ladder is
#: already four rungs and already means urgency (see
#: app/services/campaign_alerts.py's priority matrix).
ALERT_PRIORITY_SEVERITY: dict[str, str] = {
    "CRITICAL": CRITICAL,
    "HIGH": HIGH,
    "MEDIUM": MEDIUM,
    "INFO": LOW,
}

#: Risk cluster severity -> severity. Identical vocabulary; mapped through a
#: table anyway so an unknown value lands on `unknown` instead of being passed
#: through as a band the filter chips have no chip for.
RISK_SEVERITY_SEVERITY: dict[str, str] = {"high": HIGH, "medium": MEDIUM, "low": LOW}

#: Every card whose stream publishes no severity of its own carries this
#: sentence. One string, so seven cards cannot word the same caveat three ways.
NO_SEVERITY_BASIS_TR = (
    "Bu akışta şiddet verisi yok: sinyal bilgilendirme olarak listelenir. "
    "Sayıyı bir eşiğe bağlamak, akışın yayımlamadığı bir derecelendirmeyi "
    "burada uydurmak olurdu."
)

EMPTY_MESSAGE = "Bu akışta sinyal yok."

# --- where a row's "Detay" actually lands -----------------------------------
#
# One constant per stream whose target is not obvious, because these hrefs are
# read twice: once by the card on /sinyaller and once by Kokpit's Rekabet
# cells, which now link to the same place their rows came from. When the two
# drifted apart the reader paid for it -- see each constant.

#: Ağ sinyalleri. NOT bare "/hublar": that lands on the Hub'lar tab, which
#: draws a map of the desk's own hubs and no route announcements at all. The
#: tab that owns this stream is Ağ Sinyalleri, and `?view=` is what selects it
#: (frontend/src/lib/hubs.ts parses it; the Hub page has been URL-owned since
#: the İçgörüler hand-off).
NETWORK_HREF = "/hublar?view=network-signals"

#: Haber momentumu. This used to point at "/insights", and İçgörüler does not
#: draw airline momentum -- it hands the reader a digest and a signpost, and
#: says in its own docstring that the momentum is drawn on Kokpit. So the link
#: sent a reader looking for a mover to a page that never shows one.
#:
#: The full momentum list is /sinyaller itself, so the target is this page
#: narrowed to the bucket the stream files under. A bare "/sinyaller" would
#: make the card on /sinyaller link to the page it is already on; the filter
#: makes it a real move (and Kokpit's Rekabet cell uses the same string).
MOMENTUM_HREF = "/sinyaller?kind=competitor"

# --- how much of each stream reaches the list -------------------------------
#
# Caps, not filters: every stream is already ordered by its own surface's
# ranking, so taking the head keeps the strongest rows. They exist so one busy
# stream cannot bury the other six -- a quiet day for campaigns must not mean a
# page made entirely of route announcements.

CAMPAIGN_ALERT_LIMIT = 12
RISK_LIMIT = 8
RIVAL_LIMIT = 6
STRATEGIC_LIMIT = 8
NETWORK_LIMIT = 8
MOMENTUM_LIMIT = 5

#: The news lookback the BİZ-derived streams use. Same 30 days /biz itself
#: defaults to, so a rival's count here equals the count that page showed.
NEWS_WINDOW_DAYS = 30


def _parse(stamp: str | None) -> datetime | None:
    """An ISO string from a stream that already serialised its own timestamps.

    None rather than `now` on anything unparseable: "we do not know when" and
    "just now" are different facts, and defaulting the first to the second
    would put undated rows at the top of a recency sort.
    """
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _epoch(stamp: datetime | None) -> float:
    """Sort key for a nullable timestamp. Undated rows sort last rather than
    first, which is what `float("-inf")` buys over a bare 0 on a page whose
    timestamps are all in the past anyway."""
    return stamp.timestamp() if stamp else float("-inf")


# --- stream builders (pure) -------------------------------------------------
# Each takes an already-fetched stream and returns finished rows. No I/O, so
# every mapping below is directly unit-testable against a hand-built stream.


def from_cockpit(tiles) -> list[SignalOut]:
    """Kokpit's four Sinyal Panosu tiles, as cards.

    `method_tr` becomes `severity_basis_tr` verbatim: the tile already prints
    the threshold table it banded on, and restating it in this module's words
    would be a second copy of a number nobody would keep in step.
    """
    kinds = {"fx": MARKET, "fuel": MARKET, "risk": RISK, "competitor": COMPETITOR}
    rows: list[SignalOut] = []
    for tile in tiles:
        severity = COCKPIT_LEVEL_SEVERITY.get(tile.level, UNKNOWN)
        kind = kinds.get(tile.key, MARKET)
        rows.append(
            SignalOut(
                id=f"kokpit:{tile.key}",
                stream="kokpit",
                kind=kind,
                kind_label_tr=KIND_LABELS_TR[kind],
                type_label_tr=tile.label_tr,
                severity=severity,
                severity_label_tr=SEVERITY_LABELS_TR[severity],
                severity_basis_tr=tile.method_tr,
                title_tr=f"{tile.label_tr}: {tile.value_label} · {tile.level_label_tr}",
                detail_tr=tile.reason_tr,
                detected_at=tile.as_of,
                source_label=tile.source,
                href=tile.href,
            )
        )
    return rows


def from_campaign_alerts(alerts) -> list[SignalOut]:
    """The unacknowledged campaign alert inbox. `title_tr` is already a full
    Turkish sentence, composed once at generation time (see
    app/services/campaign_alerts.py) -- never recomposed here."""
    rows: list[SignalOut] = []
    for alert in alerts:
        severity = ALERT_PRIORITY_SEVERITY.get(alert.priority, UNKNOWN)
        detail = alert.detail_json or {}
        code = detail.get("airline_code")
        rows.append(
            SignalOut(
                id=f"campaign:{alert.id}",
                stream="campaign_alerts",
                kind=COMPETITOR,
                kind_label_tr=KIND_LABELS_TR[COMPETITOR],
                type_label_tr=ALERT_TYPE_LABELS_TR.get(alert.alert_type, alert.alert_type),
                severity=severity,
                severity_label_tr=SEVERITY_LABELS_TR[severity],
                severity_basis_tr=(
                    "Kampanya uyarı önceliği: rakip taşıyıcı, %40+ indirim, flash "
                    "kampanya ve 7 günden kısa satış penceresi yükselticileri "
                    "sayılarak belirlenir."
                ),
                title_tr=alert.title_tr,
                airline_codes=[code] if isinstance(code, str) and code else [],
                detected_at=alert.created_at,
                source_label="AeroIntel kampanya tespiti",
                href="/kampanyalar",
            )
        )
    return rows


def from_risk_radar(radar: RiskRadarOut, limit: int = RISK_LIMIT) -> list[SignalOut]:
    """High-severity clusters out of the Risk Radarı rollup.

    The same rollup Kokpit's risk tile counted (it is passed the very same
    object), so the tile's "3 yüksek şiddetli" and the three cards under it can
    never be two different threes.

    Freshest first among equals: `is_fresh` is the radar's own "broke in the
    last 24h", and an early-warning list that put a two-week-old cluster above
    this morning's would be sorting by nothing a reader cares about.
    """
    items = [
        item
        for country in radar.countries
        for item in country.items
        if item.severity == "high"
    ]
    items.sort(
        key=lambda i: (
            not i.is_fresh,
            -(i.published_at.timestamp() if i.published_at else 0.0),
        )
    )
    rows: list[SignalOut] = []
    for item in items[:limit]:
        severity = RISK_SEVERITY_SEVERITY.get(item.severity, UNKNOWN)
        rows.append(
            SignalOut(
                id=f"risk:{item.id}",
                stream="risk",
                kind=RISK,
                kind_label_tr=KIND_LABELS_TR[RISK],
                type_label_tr=item.risk_type_label_tr,
                severity=severity,
                severity_label_tr=SEVERITY_LABELS_TR[severity],
                severity_basis_tr=(
                    "Risk Radarı'nın kendi şiddet sınıflandırması; kümedeki en "
                    "şiddetli anlatım kazanır (bkz. /risk-radari)."
                ),
                title_tr=item.headline,
                detail_tr=item.summary_tr,
                region=item.region,
                detected_at=item.published_at,
                confidence_score=item.confidence_score,
                source_label=item.source_name or "AeroIntel risk sınıflandırması",
                href="/risk-radari",
            )
        )
    return rows


def from_rival_events(groups, limit: int = RIVAL_LIMIT) -> list[SignalOut]:
    """BİZ's per-rival published-event counts, one card per rival.

    Kept per rival rather than per event on purpose: the question this stream
    answers is "which competitor is the news suddenly about", and thirty
    individual headlines would answer a different one badly.
    """
    rows: list[SignalOut] = []
    for group in groups[:limit]:
        events = group.get("events") or []
        newest = max((_parse(e.get("last_seen")) for e in events), default=None, key=_epoch)
        rows.append(
            SignalOut(
                id=f"rival:{group['airline_code']}",
                stream="rival_events",
                kind=COMPETITOR,
                kind_label_tr=KIND_LABELS_TR[COMPETITOR],
                type_label_tr="Rakip haber hacmi",
                severity=LOW,
                severity_label_tr=SEVERITY_LABELS_TR[LOW],
                severity_basis_tr=NO_SEVERITY_BASIS_TR,
                title_tr=f"{group['airline_name']}: {group['count']} yayımlanmış olay",
                detail_tr=(events[0].get("headline") if events else None),
                region=(events[0].get("region") if events else None),
                airline_codes=[group["airline_code"]],
                detected_at=newest,
                source_label="AeroIntel olay hattı (pipeline v2)",
                # The Gazete's carrier filter is the real "everything about this
                # rival" view; /biz no longer holds one.
                href=f"/newspaper?airline={group['airline_code']}",
            )
        )
    return rows


def from_strategic(events, limit: int = STRATEGIC_LIMIT) -> list[SignalOut]:
    """Finance / fleet / sustainability / regulatory events -- BİZ's "Stratejik
    Gelişmeler", unchanged in content.

    `href` is None on purpose: BİZ was this stream's page and no longer renders
    it, so there is nowhere deeper to send the reader. A link to a Gazete tab
    would be wrong for two of the four categories, which the paper excludes.
    """
    rows: list[SignalOut] = []
    for event in events[:limit]:
        category = event.get("category")
        rows.append(
            SignalOut(
                id=f"strategic:{event['id']}",
                stream="strategic",
                kind=FINANCIAL,
                kind_label_tr=KIND_LABELS_TR[FINANCIAL],
                type_label_tr=CATEGORY_LABELS_TR.get(category or "", "Stratejik gelişme"),
                severity=LOW,
                severity_label_tr=SEVERITY_LABELS_TR[LOW],
                severity_basis_tr=NO_SEVERITY_BASIS_TR,
                title_tr=event.get("headline") or "Başlıksız gelişme",
                region=event.get("region"),
                detected_at=_parse(event.get("last_seen")),
                source_label="AeroIntel olay hattı (pipeline v2)",
                href=None,
            )
        )
    return rows


def from_network(groups, limit: int = NETWORK_LIMIT) -> list[SignalOut]:
    """New-route announcements, flattened out of the Hub page's per-region
    grouping. One card per announcement -- a route IS the signal here, unlike
    the rival stream where the count is."""
    rows: list[SignalOut] = []
    for group in groups:
        for article in group.get("articles") or []:
            if len(rows) >= limit:
                return rows
            rows.append(
                SignalOut(
                    id=f"network:{article['id']}",
                    stream="network",
                    kind=MARKET,
                    kind_label_tr=KIND_LABELS_TR[MARKET],
                    type_label_tr="Yeni hat",
                    severity=LOW,
                    severity_label_tr=SEVERITY_LABELS_TR[LOW],
                    severity_basis_tr=NO_SEVERITY_BASIS_TR,
                    title_tr=article.get("headline") or "Başlıksız hat duyurusu",
                    region=group.get("region"),
                    airline_codes=[c for c in (article.get("airlines") or []) if c],
                    detected_at=_parse(article.get("published_at")),
                    source_label=article.get("source_name") or "AeroIntel olay hattı",
                    href=NETWORK_HREF,
                )
            )
    return rows


def from_momentum(movers, limit: int = MOMENTUM_LIMIT) -> list[SignalOut]:
    """Rivals the news volume moved on, last 7 days vs the 7 before.

    Rivals only, for the reason the Kokpit tile filters the same list: a
    "Rakip" card naming the home carrier as its top mover would be plainly
    wrong. A mover with `delta == 0` is not a mover and contributes nothing.
    """
    rows: list[SignalOut] = []
    for mover in movers:
        if len(rows) >= limit:
            break
        if mover["code"] not in RIVAL_CODES or not mover["delta"]:
            continue
        rows.append(
            SignalOut(
                id=f"momentum:{mover['code']}",
                stream="momentum",
                kind=COMPETITOR,
                kind_label_tr=KIND_LABELS_TR[COMPETITOR],
                type_label_tr="Haber momentumu",
                severity=LOW,
                severity_label_tr=SEVERITY_LABELS_TR[LOW],
                severity_basis_tr=NO_SEVERITY_BASIS_TR,
                title_tr=(
                    f"{mover['name']} haber hacmi {mover['delta']:+d} "
                    f"({mover['previous']}→{mover['current']})"
                ),
                detail_tr=(
                    f"Son {MOMENTUM_WINDOW_DAYS} gün, önceki {MOMENTUM_WINDOW_DAYS} güne "
                    "göre. Haber hacmi ölçüsüdür; kapasite ya da pazar payı değildir."
                ),
                airline_codes=[mover["code"]],
                # A rolling window has no point reading, so no timestamp is
                # claimed for it -- see SignalOut.detected_at.
                detected_at=None,
                source_label="AeroIntel haber akışı",
                href=MOMENTUM_HREF,
            )
        )
    return rows


def sort_signals(rows: list[SignalOut]) -> list[SignalOut]:
    """Severity first, recency second -- the order the page is read in.

    A CRITICAL campaign alert from this morning outranks a LOW route
    announcement from ten minutes ago, and sorting by time alone would bury the
    one line that mattered under five that did not. The same argument
    /campaign-alerts makes for its own ordering.
    """
    return sorted(
        rows,
        key=lambda row: (_SEVERITY_RANK.get(row.severity, len(SEVERITY_ORDER)), -_epoch(row.detected_at)),
    )


# --- orchestration (I/O) ----------------------------------------------------

#: (key, Turkish label, kind) for every contributing stream, in the order the
#: page lists them. Data rather than seven hand-written literals, so the
#: "streams" block of the response cannot fall out of step with what actually
#: ran.
STREAMS: tuple[tuple[str, str, str], ...] = (
    ("kokpit", "Kokpit sinyal panosu", MARKET),
    ("campaign_alerts", "Kampanya uyarıları", COMPETITOR),
    ("risk", "Risk Radarı", RISK),
    ("rival_events", "Rakip olayları", COMPETITOR),
    ("strategic", "Stratejik gelişmeler", FINANCIAL),
    ("network", "Ağ sinyalleri", MARKET),
    ("momentum", "Haber momentumu", COMPETITOR),
)


async def unified_signals(db: AsyncSession, *, days: int = NEWS_WINDOW_DAYS) -> SignalsOut:
    """Compose every stream into one sorted list, plus a per-stream tally.

    The risk rollup is computed once and handed to `cockpit_signals` rather
    than fetched by both: clustering a 14-day window is the expensive half of
    this request, and running it twice would also let the tile's count and the
    cards beside it disagree.

    ONE REQUEST FEEDS BOTH SURFACES. /sinyaller draws the whole filterable
    list; Kokpit draws counts and heads of it (its signal board, its alert
    band, its Rekabet cells) plus the four tiles. Kokpit used to reach that
    state through five more requests of its own -- /kokpit/signals,
    /campaign-alerts, /risks, /insights and /hubs/network-signals -- which is
    how the two pages came to sort the same rows differently and show a
    different "top four". They read this response now, so a row on Kokpit is
    the same object, in the same order, as the row on /sinyaller.

    That is also why `cockpit_tiles` rides along: the tiles are already
    computed here, and flattening them into `SignalOut` loses the fields
    Kokpit's cells draw (see SignalsOut.cockpit_tiles).
    """
    radar = await aggregate_risks(db, days=RISK_WINDOW_DAYS)

    # Read ONCE and handed to both consumers, for the same two reasons `radar`
    # is: it is two grouped joins over articles x entities, and two calls would
    # anchor their 7-vs-7 windows on two readings of the clock -- so the Kokpit
    # tile could name a top mover the momentum cards beside it rank differently.
    movers = await airline_momentum(db, window_days=MOMENTUM_WINDOW_DAYS, limit=20)

    tiles = await cockpit_signals(db, radar=radar, momentum=movers)
    # Held rather than passed straight through: the region groups carry a
    # count for the whole region, and `from_network` only sees the head it is
    # allowed to list. See `totals` below.
    route_groups = await network_signals(db, days=days)

    by_stream: dict[str, list[SignalOut]] = {
        "kokpit": from_cockpit(tiles),
        "campaign_alerts": from_campaign_alerts(
            await open_alerts(db, limit=CAMPAIGN_ALERT_LIMIT)
        ),
        "risk": from_risk_radar(radar),
        "rival_events": from_rival_events(await competitor_signals(db, days=days)),
        "strategic": from_strategic(await strategic_developments(db, days=days)),
        "network": from_network(route_groups),
        "momentum": from_momentum(movers),
    }

    #: Per-stream `total`, and ONLY where the stream's source really publishes
    #: one. `network_signals()` documents `count` as "the full regional total
    #: even when the listed articles are capped", so summing them is the
    #: worldwide 30-day figure Kokpit's route cell has always printed -- a
    #: number NETWORK_LIMIT rows can no longer supply on their own.
    #:
    #: Wider than the rows listed, but not unbounded: `network_signals()` reads
    #: at most `max_events` (120) events before grouping, so this sum is capped
    #: there too. Said out loud because the previous wording ("uncapped") was a
    #: claim the query never made.
    #:
    #: Every other stream is absent from this dict and so reports None. That is
    #: the honest answer for them: the campaign inbox is capped inside its own
    #: query, and the rest hand this module a list whose length is already the
    #: number of rows produced. Reporting `count` again as a `total` would look
    #: like a measurement and be a restatement.
    totals: dict[str, int] = {
        "network": sum(int(group.get("count") or 0) for group in route_groups),
    }

    signals = sort_signals([row for rows in by_stream.values() for row in rows])
    streams = [
        SignalStreamOut(
            key=key,
            label_tr=label,
            kind=kind,
            count=len(by_stream[key]),
            total=totals.get(key),
            available=bool(by_stream[key]),
            empty_message=None if by_stream[key] else EMPTY_MESSAGE,
        )
        for key, label, kind in STREAMS
    ]

    return SignalsOut(
        days=days,
        total=len(signals),
        signals=signals,
        streams=streams,
        cockpit_tiles=tiles,
        # The radar's own scan cap, forwarded. Kokpit's alert band and
        # /sinyaller's tally count risk rows out of this response and never
        # call /risks, so this is the ONLY channel by which they can learn
        # that those counts are floors. A cap whose disclosure has no reader
        # is a silent cap.
        risk_truncated=radar.truncated,
        risk_scanned_articles=radar.scanned_articles,
        generated_at=datetime.now(timezone.utc),
    )
