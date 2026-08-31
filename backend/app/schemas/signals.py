"""The Sinyaller page's unified signal shape.

Deliberately its own module rather than an addition to schemas/kokpit.py: the
Kokpit tiles are one of the six streams this page composes, and folding the
composite into the tile module would make it look like a Kokpit feature.
"""
from datetime import datetime

from pydantic import BaseModel


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
    count: int
    available: bool
    empty_message: str | None = None


class SignalsOut(BaseModel):
    #: The risk/news lookback the composed streams used, in days.
    days: int
    total: int
    signals: list[SignalOut]
    streams: list[SignalStreamOut]
    #: When the composition ran -- a fact about this response, not about the
    #: newest signal in it.
    generated_at: datetime
