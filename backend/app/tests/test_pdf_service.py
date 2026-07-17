"""The PDF is rendered on one machine (a CI runner with Chromium) and served by
another (the serverless API without it), so Postgres is the only handoff. These
cover that contract; Chromium itself is stubbed, since CI has no browser.
"""
from datetime import date

import pytest

from app.models.edition import Edition, EditionPdf
from app.services import pdf_service
from app.services.pdf_service import get_edition_pdf_bytes, refresh_pdf_for_date, store_edition_pdf

FAKE_PDF = b"%PDF-1.4 fake bytes"


@pytest.fixture
def chromium_renders(monkeypatch):
    async def _render(edition):
        return FAKE_PDF

    monkeypatch.setattr(pdf_service, "render_edition_pdf", _render)


@pytest.fixture
def chromium_missing(monkeypatch):
    async def _render(edition):
        return None  # what render_edition_pdf does when Playwright isn't installed

    monkeypatch.setattr(pdf_service, "render_edition_pdf", _render)


async def _make_edition(db_session, edition_date: date) -> Edition:
    edition = Edition(edition_date=edition_date, status="published", headline="Test")
    db_session.add(edition)
    await db_session.flush()
    return edition


async def test_store_writes_bytes_to_postgres_and_stamps_the_edition(db_session, chromium_renders):
    edition = await _make_edition(db_session, date(2026, 7, 1))

    assert await store_edition_pdf(db_session, edition) is True

    assert await get_edition_pdf_bytes(db_session, edition.id) == FAKE_PDF
    # The stamp is what `pdf_available` reads, so listing editions never has to
    # touch the blob table.
    assert edition.pdf_generated_at is not None


async def test_store_is_idempotent_and_overwrites_rather_than_duplicating(db_session, chromium_renders):
    from sqlalchemy import func, select

    edition = await _make_edition(db_session, date(2026, 7, 2))

    await store_edition_pdf(db_session, edition)
    await store_edition_pdf(db_session, edition)

    count = await db_session.execute(
        select(func.count()).select_from(EditionPdf).where(EditionPdf.edition_id == edition.id)
    )
    assert count.scalar_one() == 1


async def test_no_chromium_reports_failure_without_raising(db_session, chromium_missing):
    edition = await _make_edition(db_session, date(2026, 7, 3))

    # A machine without a browser must degrade to "not ready", never crash the
    # daily cycle that calls this.
    assert await store_edition_pdf(db_session, edition) is False
    assert edition.pdf_generated_at is None
    assert await get_edition_pdf_bytes(db_session, edition.id) is None


async def test_refresh_for_a_date_with_no_edition_is_a_noop(db_session, chromium_renders):
    assert await refresh_pdf_for_date(db_session, date(2026, 6, 30)) is False
