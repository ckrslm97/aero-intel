"""Renders an Edition to PDF bytes by feeding the full-edition HTML through
headless Chromium. Degrades gracefully (returns None) if Playwright's browser
isn't installed -- PDF export is a nice-to-have, not a hard dependency, and the
serverless API deliberately ships without it (see app/services/pdf_service.py).
"""
from app.core.logging import get_logger
from app.email.render import render_edition_full_html
from app.models.edition import Edition

logger = get_logger(__name__)


async def render_edition_pdf(edition: Edition) -> bytes | None:
    """Returns the PDF bytes, or None when Chromium isn't available here.

    Bytes rather than a file path: the renderer (a GitHub Actions runner) and
    the server that hands the PDF to the browser are different machines with
    no shared disk, so the result goes to Postgres, not the filesystem.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("pdf_generation_skipped_playwright_not_installed")
        return None

    html_body = render_edition_full_html(edition)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html_body, wait_until="networkidle")
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            await browser.close()
    except Exception as exc:  # noqa: BLE001 -- PDF export failure must not break the daily cycle
        logger.warning("pdf_generation_failed", error=str(exc))
        return None

    logger.info("pdf_generated", edition_date=str(edition.edition_date), bytes=len(pdf_bytes))
    return pdf_bytes
