"""Rendering a PDF and storing it are separate concerns from serving it: the
render happens on a GitHub Actions runner (which has Chromium), the serve
happens in the serverless API (which doesn't). Postgres is the handoff.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.edition import Edition, EditionPdf
from app.pdf.render import render_edition_pdf
from app.repositories.edition_repository import EditionRepository

logger = get_logger(__name__)


async def store_edition_pdf(db: AsyncSession, edition: Edition) -> bool:
    """Render `edition` and upsert the bytes into `edition_pdfs`.

    Returns False (without raising) when Chromium isn't available or rendering
    failed -- callers treat a missing PDF as "not ready yet", never as a crash.
    """
    pdf_bytes = await render_edition_pdf(edition)
    if pdf_bytes is None:
        return False

    existing = await db.execute(select(EditionPdf).where(EditionPdf.edition_id == edition.id))
    row = existing.scalar_one_or_none()
    if row is None:
        db.add(EditionPdf(edition_id=edition.id, data=pdf_bytes, byte_size=len(pdf_bytes)))
    else:
        row.data = pdf_bytes
        row.byte_size = len(pdf_bytes)

    edition.pdf_generated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("pdf_stored", edition_date=str(edition.edition_date), bytes=len(pdf_bytes))
    return True


async def get_edition_pdf_bytes(db: AsyncSession, edition_id) -> bytes | None:
    """Fetch just the blob -- never loaded via the ORM relationship, so listing
    editions stays cheap."""
    result = await db.execute(select(EditionPdf.data).where(EditionPdf.edition_id == edition_id))
    return result.scalar_one_or_none()


async def refresh_pdf_for_date(db: AsyncSession, edition_date: date) -> bool:
    """Render + store the PDF for an already-assembled edition. Used by the
    Actions jobs so today's PDF is waiting before anyone clicks download."""
    edition = await EditionRepository(db).get_by_date(edition_date)
    if edition is None:
        logger.warning("pdf_refresh_skipped_no_edition", edition_date=str(edition_date))
        return False
    return await store_edition_pdf(db, edition)
