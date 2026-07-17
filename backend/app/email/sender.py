"""Sends the rendered newsletter -- via real SMTP when SMTP_HOST is configured,
otherwise writes the HTML to ./outbox so the whole pipeline is testable with
zero email credentials.
"""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib

from app.core.config import get_settings
from app.core.db import IS_SERVERLESS
from app.core.logging import get_logger

logger = get_logger(__name__)


def _outbox_dir(configured: str) -> Path:
    # Serverless filesystems are read-only apart from /tmp, and this is only the
    # no-credentials dry-run path, so a scratch dir is the right fallback --
    # real sends go over SMTP and touch no disk.
    if IS_SERVERLESS:
        return Path("/tmp/outbox")
    return Path(__file__).parent.parent.parent / configured


async def send_email(to_email: str, subject: str, html_body: str) -> None:
    settings = get_settings()

    if not settings.smtp_host:
        outbox_dir = _outbox_dir(settings.outbox_dir)
        outbox_dir.mkdir(parents=True, exist_ok=True)
        safe_email = to_email.replace("@", "_at_")
        out_path = outbox_dir / f"{subject.replace(' ', '_')}__{safe_email}.html"
        out_path.write_text(html_body, encoding="utf-8")
        logger.info("email_dry_run_written", to=to_email, path=str(out_path))
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html"))

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_use_tls,
    )
    logger.info("email_sent", to=to_email)
