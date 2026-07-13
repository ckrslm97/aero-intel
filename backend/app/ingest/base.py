"""Source adapter contract: every ingestion source (free RSS, premium API, LinkedIn, ...)
implements this so the ingestion service never needs to know what kind of source it's talking to.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class RawArticle:
    url: str
    title: str
    content: str
    author: str | None
    published_at: datetime | None


class SourceAdapter(Protocol):
    source_name: str

    async def fetch(self) -> list[RawArticle]:
        """Fetch the latest items from this source. Must not raise -- adapters catch
        and log their own failures so one broken source never blocks the others."""
        ...
