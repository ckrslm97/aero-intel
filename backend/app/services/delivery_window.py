"""Deciding whether today's newspaper is due to go out yet.

GitHub's scheduled workflows are queued, not guaranteed. Measured on this repo
across four days, a 04:15 UTC schedule actually fired at 06:15, 06:41, 07:25
and 06:38 -- an average delay of 2h30m, worst case 3h10m. So a single cron
entry cannot deliver "every morning at nine": moving the schedule earlier just
moves the uncertainty.

Instead the workflow is scheduled repeatedly through the small hours and each
run asks this module whether it is time. The first run to wake up at or after
the target hour sends; every other run does nothing. GitHub's delay stops
mattering because we are no longer trusting it to be punctual -- only to fire
at least once inside a four-hour window.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.edition import Edition
from app.models.email_delivery import EmailDelivery

logger = get_logger(__name__)

# Istanbul is UTC+3 all year (Turkey has no DST since 2016), so a fixed offset
# is correct here and avoids depending on the runner's tzdata.
ISTANBUL_OFFSET = timedelta(hours=3)
SEND_HOUR_LOCAL = 9

# Past this hour the day is written off: a newsletter that shows up at
# midnight is worse than one that never came, and tomorrow's run should not
# inherit today's backlog.
GIVE_UP_HOUR_LOCAL = 14


def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + ISTANBUL_OFFSET


async def already_sent_today(db: AsyncSession, edition_date: date) -> bool:
    """True when at least one subscriber already has today's edition."""
    sent = (
        await db.execute(
            select(func.count(EmailDelivery.subscriber_id))
            .join(Edition, Edition.id == EmailDelivery.edition_id)
            .where(Edition.edition_date == edition_date, EmailDelivery.status == "sent")
        )
    ).scalar_one()
    return sent > 0


async def newsletter_is_due(db: AsyncSession, now: datetime | None = None) -> tuple[bool, str]:
    """Should this run send the newsletter? Returns (decision, reason).

    The reason is logged so a workflow run that does nothing still says why,
    which is what makes a schedule this noisy debuggable.
    """
    local = local_now(now)
    if local.hour < SEND_HOUR_LOCAL:
        return False, f"too early ({local:%H:%M} local, sends at {SEND_HOUR_LOCAL:02d}:00)"
    if local.hour >= GIVE_UP_HOUR_LOCAL:
        return False, f"too late ({local:%H:%M} local); today's send is abandoned"
    if await already_sent_today(db, local.date()):
        return False, "already sent today"
    return True, f"due ({local:%H:%M} local)"


def build_window_is_open(now: datetime | None = None) -> bool:
    """Whether to (re)assemble the edition and its PDF.

    Assembling is cheap and idempotent, so early runs still do it -- that way
    the edition is ready and complete the moment the send window opens, rather
    than being built from scratch at 09:00.
    """
    return local_now(now).hour < GIVE_UP_HOUR_LOCAL


__all__ = [
    "GIVE_UP_HOUR_LOCAL",
    "SEND_HOUR_LOCAL",
    "already_sent_today",
    "build_window_is_open",
    "local_now",
    "newsletter_is_due",
]
