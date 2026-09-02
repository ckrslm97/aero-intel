"""Source adapter contract: every ingestion source (free RSS, premium API, LinkedIn, ...)
implements this so the ingestion service never needs to know what kind of source it's talking to.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class RawArticle:
    url: str
    title: str
    content: str
    author: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class FetchHealth:
    """What one fetch attempt did, for the `sources` health columns.

    Reported OUT-OF-BAND rather than by changing `fetch()`'s return type: the
    adapter contract is that a broken source returns an empty list and never
    raises, and every caller and every premium adapter is built on that. An
    adapter that wants to be measured sets `last_health` (see the Protocol
    below); one that doesn't, isn't, and the health columns stay untouched
    rather than being filled with guesses.

    `ok` is not "the request succeeded" but "this run produced usable
    articles". A 200 carrying an HTML page where the feed used to be is a
    failure here, which is the same judgement rss.py's `rss_no_usable_entries`
    warning already makes -- and the whole reason these columns exist, since
    FAA and ICAO died exactly that way and looked healthy for months.
    """

    ok: bool
    #: None when there was no HTTP response at all (DNS, TLS, timeout), which
    #: is a genuinely different failure from an answered 403.
    http_status: int | None = None
    article_count: int = 0
    at: datetime | None = None

    def __post_init__(self) -> None:
        if self.at is None:
            object.__setattr__(self, "at", datetime.now(timezone.utc))


class SourceAdapter(Protocol):
    source_name: str

    #: Set by adapters that report health; absent on those that don't, so
    #: callers must use getattr(). Optional by design -- see FetchHealth.
    last_health: FetchHealth | None

    async def fetch(self) -> list[RawArticle]:
        """Fetch the latest items from this source. Must not raise -- adapters catch
        and log their own failures so one broken source never blocks the others."""
        ...
