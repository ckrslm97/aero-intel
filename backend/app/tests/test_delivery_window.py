"""The nine-o'clock guard.

GitHub queues scheduled workflows: measured on this repo, a 04:15 UTC schedule
fired at 06:15, 06:41, 07:25 and 06:38 on four consecutive days. The workflow
therefore knocks repeatedly and this module decides which knock delivers.
"""
from datetime import datetime, timezone

from app.models.edition import Edition
from app.models.email_delivery import EmailDelivery
from app.models.subscriber import Subscriber
from app.services.delivery_window import (
    build_window_is_open,
    local_now,
    newsletter_is_due,
)


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 22, hour, minute, tzinfo=timezone.utc)


def test_istanbul_is_three_hours_ahead():
    assert local_now(_utc(6, 0)).hour == 9


async def test_a_run_before_nine_does_not_send(db_session):
    # 05:30 UTC = 08:30 Istanbul -- the newspaper is not due yet.
    due, reason = await newsletter_is_due(db_session, _utc(5, 30))
    assert due is False
    assert "too early" in reason


async def test_the_first_run_at_or_after_nine_sends(db_session):
    due, reason = await newsletter_is_due(db_session, _utc(6, 0))
    assert due is True
    assert "due" in reason


async def test_a_late_delivery_still_goes_out(db_session):
    """GitHub's worst measured delay was 3h10m. A run that finally wakes at
    10:25 local must still deliver -- that is the whole point of the window."""
    due, _ = await newsletter_is_due(db_session, _utc(7, 25))
    assert due is True


async def test_later_runs_do_nothing_once_it_has_gone_out(db_session):
    """Eight scheduled runs, one newsletter."""
    subscriber = Subscriber(email="reader@example.com", is_active=True)
    edition = Edition(
        edition_date=local_now(_utc(6, 0)).date(),
        headline="Bugünün manşeti",
        executive_summary="",
        status="published",
    )
    db_session.add_all([subscriber, edition])
    await db_session.flush()
    db_session.add(
        EmailDelivery(
            subscriber_id=subscriber.id, edition_id=edition.id,
            status="sent", sent_at=_utc(6, 1),
        )
    )
    await db_session.commit()

    due, reason = await newsletter_is_due(db_session, _utc(6, 40))
    assert due is False
    assert "already sent" in reason


async def test_a_pending_delivery_does_not_count_as_sent(db_session):
    """A failed or queued send must not block the retry."""
    subscriber = Subscriber(email="reader2@example.com", is_active=True)
    edition = Edition(
        edition_date=local_now(_utc(6, 0)).date(),
        headline="Bugünün manşeti", executive_summary="", status="published",
    )
    db_session.add_all([subscriber, edition])
    await db_session.flush()
    db_session.add(
        EmailDelivery(subscriber_id=subscriber.id, edition_id=edition.id, status="failed")
    )
    await db_session.commit()

    due, _ = await newsletter_is_due(db_session, _utc(6, 40))
    assert due is True


async def test_the_day_is_abandoned_rather_than_sent_at_midnight(db_session):
    """A newsletter arriving at 3am is worse than one that never came."""
    due, reason = await newsletter_is_due(db_session, _utc(20, 0))  # 23:00 local
    assert due is False
    assert "too late" in reason


def test_early_runs_still_keep_the_edition_warm():
    """Assembling is idempotent and cheap, so it happens on every run in the
    window -- the send, when it comes, should be instant."""
    assert build_window_is_open(_utc(3, 0)) is True   # 06:00 local
    assert build_window_is_open(_utc(6, 0)) is True   # 09:00 local
    assert build_window_is_open(_utc(20, 0)) is False  # 23:00 local
