"""The Sinyaller page's unified signal shape.

Deliberately its own module rather than an addition to schemas/kokpit.py: the
Kokpit tiles are one of the seven streams this page composes, and folding the
composite into the tile module would make it look like a Kokpit feature. The
dependency runs the other way -- this envelope IMPORTS `CockpitSignalOut` (see
`SignalsOut.cockpit_tiles`) rather than kokpit importing anything from here.
"""
from datetime import datetime

from pydantic import BaseModel

from app.schemas.kokpit import CockpitSignalOut


class SignalOut(BaseModel):
    """One row of the early-warning list, from whichever stream produced it.

    Every field here is carried FROM a stream, never computed as a new
    judgement about it. In particular `severity` is a band the owning stream
    already published (a campaign alert's priority, a risk signal's severity, a
    Kokpit tile's level), and `severity_basis_tr` says which -- a stream with
    no severity of its own is mapped to `low` and says so in as many words
    rather than being given a number this page invented.
    """

    #: Stable within one response; prefixed with the stream key so two streams
    #: cannot collide on an underlying row id.
    id: str
    #: Which stream produced this row -- see app/services/signals_service.py
    #: STREAMS for the full list and what each one reads.
    stream: str
    #: market | risk | competitor | financial.
    kind: str
    kind_label_tr: str
    #: What kind of thing this is inside its stream ("Yeni hat", "Kur Riski",
    #: "Bitmek üzere"), in Turkish, taken from the stream's own vocabulary.
    type_label_tr: str
    #: critical | high | medium | low | unknown. `unknown` is not a band: it
    #: means the driver could not be read at all, and must never render as an
    #: all-clear.
    severity: str
    severity_label_tr: str
    #: How `severity` was arrived at, verbatim, for the card's ⓘ note.
    severity_basis_tr: str
    title_tr: str
    #: The sentence under the title, where the stream has one.
    detail_tr: str | None = None
    #: World-region slug, where the stream resolved one.
    region: str | None = None
    #: IATA codes the signal is about. Empty for a macro signal.
    airline_codes: list[str] = []
    #: When the signal was detected/published. None where the stream is a
    #: rolling window with no point reading -- never defaulted to now.
    detected_at: datetime | None = None
    #: 0-1, only where the owning stream actually carries one (risk clusters
    #: do; a campaign alert does not). Never synthesised.
    confidence_score: float | None = None
    #: Where the number came from, as the owning surface states it.
    source_label: str
    #: In-app drill-down to the page that owns this signal.
    href: str | None = None


class SignalStreamOut(BaseModel):
    """One contributing stream, present whether or not it produced anything.

    The same structural no-filler rule biz_service._section() enforces: a
    stream that found nothing says so with its own sentence, so the page can
    print "Bu akışta sinyal yok" instead of silently omitting the stream and
    leaving the reader unable to tell "nothing happened" from "it broke".
    """

    key: str
    label_tr: str
    kind: str
    #: Rows from this stream in THIS response's `signals` list -- i.e. after the
    #: per-stream display cap in signals_service.py.
    count: int
    #: What the stream's own source measured, where that source publishes a
    #: figure that can exceed the rows listed here. Only `network` has one
    #: today: `network_signals()` counts a whole region even when it lists only
    #: `per_region` of its articles, and Kokpit's route cell prints the sum.
    #:
    #: It exceeds the rows listed, but it is NOT unbounded, and this comment
    #: used to say it was: `network_signals()` selects at most `max_events`
    #: (120) events before grouping, so the per-region counts -- and therefore
    #: their sum -- are themselves capped there. It is the widest number this
    #: stream can honestly publish, not a total over all time.
    #:
    #: None means "this stream publishes no figure beyond the rows it produced"
    #: -- NOT zero, and it must never be rendered as one. A stream whose source
    #: is itself query-limited (the campaign alert inbox) deliberately stays
    #: None rather than reporting its own limit as a total.
    total: int | None = None
    available: bool
    empty_message: str | None = None


class SignalsOut(BaseModel):
    #: The risk/news lookback the composed streams used, in days.
    days: int
    total: int
    signals: list[SignalOut]
    streams: list[SignalStreamOut]
    #: The `kokpit` stream in ITS OWN shape, beside the flattened rows.
    #:
    #: Not a duplicate: `SignalOut` is deliberately lossy about a tile. It
    #: composes the label, the value and the band into one sentence
    #: (`title_tr`) and maps the tile's four-rung `level` onto this page's
    #: five-rung `severity`, which is the right trade for a card in a mixed
    #: list and the wrong one for Kokpit's Market Pulse cells and Günün Özeti
    #: tiles, which draw `level`, `value_label` and `method_tr` separately.
    #:
    #: Carrying both here is what lets Kokpit read ONE endpoint. Before this,
    #: the page fetched `/kokpit/signals` as well, and the 14-day risk
    #: clustering behind the risk tile ran a second time -- for tiles that are
    #: banded from the very same rollup this response already computed.
    cockpit_tiles: list[CockpitSignalOut] = []
    #: True when the risk rollup behind this response hit its own scan cap
    #: (`RiskRadarOut.truncated`, see api/v1/risks.py RISK_SCAN_CAP).
    #:
    #: Carried here rather than left inside /risks because Kokpit and
    #: /sinyaller never read /risks: they count risk rows out of THIS envelope,
    #: and when the cap bit those counts are FLOORS over the newest slice of
    #: the risk window. A surface printing them owes the reader "hepsi bu kadar
    #: değil"; without this field it has no way to know it owes anything.
    risk_truncated: bool = False
    #: How many articles that rollup actually read -- equal to the radar's cap
    #: when `risk_truncated`. Served so the disclosure can name a number
    #: instead of expecting the reader to know the cap.
    risk_scanned_articles: int = 0
    #: When the composition ran -- a fact about this response, not about the
    #: newest signal in it.
    generated_at: datetime
