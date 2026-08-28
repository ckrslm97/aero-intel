"""One row per fetch attempt: scraper telemetry, kept because the failures are
the data.

Six of the seven carriers we want (TK, AJet, QR, EK, EY, BA) sit behind bot
walls that a plain httpx GET cannot pass; only Pegasus answers statically. That
is not a bug to fix once -- walls come and go, a carrier that worked in March
starts returning a challenge page in June, and the failure is silent: the
fetcher gets 200 OK and a body containing nothing but JavaScript. Without a
record of attempts, "no new TK campaigns this week" and "we have not
successfully read TK's page since Tuesday" look identical.

So every attempt writes a row whether it succeeded or not, and `outcome` is the
column the carrier list is maintained from: a carrier that turns to `blocked`
gets demoted to its newsroom tier instead of quietly disappearing from the
page. `content_hash` and `changed` also make this the LLM budget ledger --
extraction runs only for the runs where `changed` is true.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPrimaryKeyMixin


class ScrapeRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        # The question this table is asked: "how did <carrier> last do?" --
        # newest run per carrier, for the admin health view and for deciding
        # whether to keep trying a walled page.
        Index("ix_scrape_runs_carrier_started", "carrier_code", "started_at"),
    )

    carrier_code: Mapped[str] = mapped_column(String(6), index=True)
    url: Mapped[str] = mapped_column(String(500))
    #: static | browser -- an httpx GET or a real chromium page load. Recorded
    #: because the interesting comparison is which method got through.
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: NULL while a run is in flight, and still NULL if the job was killed --
    #: which is itself the signal that a page hangs.
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: ok | blocked | timeout | parse_error. Indexed: the health view filters on
    #: it, and `blocked` is the value that changes the carrier registry.
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    #: Kept next to `outcome` rather than folded into it, because a bot wall
    #: answers 200 -- the status code alone never tells you what happened.
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: sha256 of the extracted text, compared against the previous ok run.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Whether that hash moved. NULL when there is nothing to compare against
    #: (first ever run, or a run that never got a body), which is not the same
    #: as "unchanged".
    changed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
