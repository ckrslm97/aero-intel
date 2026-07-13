"""Daily edition endpoints. Today's edition auto-assembles on first request if
it doesn't exist yet; past dates are immutable once built.
"""
import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
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
        pdf_available=bool(edition.pdf_path and os.path.exists(edition.pdf_path)),
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
            pdf_available=bool(e.pdf_path and os.path.exists(e.pdf_path)),
        )
        for e in editions
    ]


@router.get("/{edition_date}", response_model=EditionOut)
async def get_edition(edition_date: date, db: AsyncSession = Depends(get_db)) -> EditionOut:
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)

    if edition is None:
        if edition_date != date.today():
            raise HTTPException(status_code=404, detail="Edition not found")
        edition = await assemble_edition(db, edition_date)
        edition = await repo.get_by_date(edition_date)

    return _to_edition_out(edition)


@router.get("/{edition_date}/pdf")
async def download_edition_pdf(edition_date: date, db: AsyncSession = Depends(get_db)) -> FileResponse:
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)

    if edition is None or not edition.pdf_path or not os.path.exists(edition.pdf_path):
        raise HTTPException(status_code=404, detail="PDF not available for this edition")

    return FileResponse(
        edition.pdf_path,
        media_type="application/pdf",
        filename=f"aerointel-{edition_date}.pdf",
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
