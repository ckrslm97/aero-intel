"""Daily edition endpoints. Today's edition auto-assembles on first request if
it doesn't exist yet; past dates are immutable once built.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_roles
from app.models.edition import Edition
from app.repositories.edition_repository import EditionRepository
from app.schemas.article import ArticleOut
from app.schemas.edition import EditionOut, EditionSectionOut, EditionSummaryOut
from app.services.edition_service import assemble_edition

router = APIRouter(prefix="/editions", tags=["editions"])


def _to_edition_out(edition: Edition) -> EditionOut:
    sections: dict[str, list[ArticleOut]] = {}
    for edition_article in sorted(edition.articles, key=lambda ea: (ea.section, ea.rank)):
        sections.setdefault(edition_article.section, []).append(
            ArticleOut.model_validate(edition_article.article)
        )

    ordered_sections = []
    if "top_story" in sections:
        ordered_sections.append(EditionSectionOut(section="top_story", articles=sections.pop("top_story")))
    for section, articles in sections.items():
        ordered_sections.append(EditionSectionOut(section=section, articles=articles))

    return EditionOut(
        id=edition.id,
        edition_date=edition.edition_date,
        status=edition.status,
        headline=edition.headline,
        executive_summary=edition.executive_summary,
        sections=ordered_sections,
        pdf_available=edition.pdf_generated_at is not None,
    )


@router.get("", response_model=list[EditionSummaryOut])
async def list_editions(db: AsyncSession = Depends(get_db)) -> list[EditionSummaryOut]:
    repo = EditionRepository(db)
    editions = await repo.list_recent()
    return [
        EditionSummaryOut(
            id=e.id,
            edition_date=e.edition_date,
            status=e.status,
            headline=e.headline,
            story_count=len(e.articles),
            pdf_available=e.pdf_generated_at is not None,
        )
        for e in editions
    ]


@router.get("/{edition_date}", response_model=EditionOut)
async def get_edition(edition_date: date, db: AsyncSession = Depends(get_db)) -> EditionOut:
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)

    if edition is None:
        # Compare against the UTC day: article timestamps are UTC, so the
        # local calendar would auto-assemble an empty edition between local
        # and UTC midnight.
        if edition_date != datetime.now(timezone.utc).date():
            raise HTTPException(status_code=404, detail="Edition not found")
        edition = await assemble_edition(db, edition_date)
        edition = await repo.get_by_date(edition_date)

    return _to_edition_out(edition)


@router.get("/{edition_date}/pdf")
async def download_edition_pdf(edition_date: date, db: AsyncSession = Depends(get_db)) -> Response:
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)
    if edition is None:
        raise HTTPException(status_code=404, detail="Edition not found")

    # Lazy: pdf_service -> pdf/render -> email/render builds a Jinja2
    # Environment at import time, which no other endpoint needs.
    from app.services.pdf_service import get_edition_pdf_bytes

    pdf_bytes = await get_edition_pdf_bytes(db, edition.id)
    if pdf_bytes is None:
        # Rendering needs Chromium, which only the GitHub Actions runner has --
        # so a PDF that hasn't been generated yet is a "not ready", not an error.
        raise HTTPException(status_code=404, detail="PDF not generated for this edition yet")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="aerointel-gazete-{edition_date}.pdf"'
        },
    )


@router.post(
    "/{edition_date}/rebuild",
    response_model=EditionOut,
    dependencies=[Depends(require_roles("admin", "editor"))],
)
async def rebuild_edition(edition_date: date, db: AsyncSession = Depends(get_db)) -> EditionOut:
    await assemble_edition(db, edition_date)
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)
    return _to_edition_out(edition)
