"""Sends the daily newsletter to every active subscriber and logs delivery
status. Safe to re-run: pending/failed deliveries for an edition are retried
on each call (up to MAX_ATTEMPTS) rather than re-sent to subscribers who
already received it.
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.email.render import render_newsletter_html
from app.email.sender import send_email
from app.models.edition import Edition
from app.repositories.email_delivery_repository import EmailDeliveryRepository
from app.repositories.subscriber_repository import SubscriberRepository

logger = get_logger(__name__)

MAX_ATTEMPTS = 5


async def send_newsletter_for_edition(db: AsyncSession, edition: Edition) -> dict:
    subscriber_repo = SubscriberRepository(db)
    delivery_repo = EmailDeliveryRepository(db)

    subscribers = await subscriber_repo.list_active()
    for subscriber in subscribers:
        await delivery_repo.get_or_create(subscriber.id, edition.id)
    await db.commit()

    html_body = render_newsletter_html(edition)
    subject = f"AeroIntel Daily — {edition.headline}"

    retriable = await delivery_repo.list_retriable_for_edition(edition.id)
    sent, failed, skipped = 0, 0, 0

    for delivery in retriable:
        if delivery.attempts >= MAX_ATTEMPTS:
            skipped += 1
            continue

        subscriber = next((s for s in subscribers if s.id == delivery.subscriber_id), None)
        if subscriber is None:
            continue

        delivery.attempts += 1
        try:
            await send_email(subscriber.email, subject, html_body)
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
            delivery.last_error = None
            sent += 1
        except Exception as exc:  # noqa: BLE001 -- one bad address must not stop the run
            delivery.status = "failed"
            delivery.last_error = str(exc)
            failed += 1
            logger.warning("newsletter_send_failed", to=subscriber.email, error=str(exc))

    await db.commit()
    logger.info("newsletter_run_complete", sent=sent, failed=failed, skipped=skipped)
    return {"sent": sent, "failed": failed, "skipped": skipped}
