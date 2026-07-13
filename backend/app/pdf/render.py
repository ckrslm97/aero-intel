"""Renders an Edition to PDF by feeding the same newsletter HTML through
headless Chromium. Degrades gracefully (returns None) if Playwright's browser
isn't installed -- PDF export is a nice-to-have, not a hard dependency.
"""
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.email.render import render_newsletter_html
from app.models.edition import Edition

logger = get_logger(__name__)


async def render_edition_pdf(edition: Edition) -> str | None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("pdf_generation_skipped_playwright_not_installed")
        return None

    html_body = render_newsletter_html(edition)
    settings = get_settings()
    storage_dir = Path(__file__).parent.parent.parent / settings.storage_local_dir / "pdfs"
    storage_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = storage_dir / f"{edition.edition_date}.pdf"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html_body, wait_until="networkidle")
            await page.pdf(path=str(pdf_path), format="A4", print_background=True)
            await browser.close()
    except Exception as exc:  # noqa: BLE001 -- PDF export failure must not break the daily cycle
        logger.warning("pdf_generation_failed", error=str(exc))
        return None

    logger.info("pdf_generated", path=str(pdf_path))
    return str(pdf_path)
