"""Daily edition endpoints.

READING AN EDITION NEVER BUILDS ONE. GET /editions/{date} used to assemble the
day's edition on the first request that missed -- a public, unauthenticated
read that wrote rows and spent an LLM call. Three things were wrong with it:

* `editions.edition_date` is UNIQUE, so two readers arriving together both saw
  "no edition", both inserted, and the loser got a 500 out of an IntegrityError
  -- worst exactly when the paper is most read, the morning of a fresh day.
* Assembly ranks every enriched article of the day and calls the summariser.
  That is minutes of work in the worst case, inside a request budget measured
  in tens of seconds, paid by whoever happened to arrive first.
* A write cannot be cached, so the one endpoint that serves a finished,
  unchanging document could not be served from the edge at all.

Assembly belongs to the cron that already owns it: .github/workflows/
jobs-daily-edition.yml runs `python -m app.cli daily-if-due`, and an operator
can force one day with POST /editions/{date}/rebuild. So a GET that finds
nothing says so -- "henüz hazırlanmadı" for a day that is still to come, plain
not-found for a past day nobody built -- and never turns a reader into a
publisher.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import FRESH, archive_cache, public_cache
from app.api.deps import require_admin
from app.core.db import get_db
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


#: `detail.code` on the two 404s below, so a client can tell "the paper for
#: this day has not been put together yet" apart from "there is no such paper".
#: The distinction is real and only the server can draw it: the assembly job
#: builds today, so a day that has not arrived at the job yet will get an
#: edition, and a past day that has none never will unless an operator rebuilds
#: it. Without the code, the page can only render one message for both, and the
#: honest one for today ("henüz hazırlanmadı") is a lie about 2024.
NOT_PREPARED = "not_prepared_yet"
NOT_FOUND = "not_found"


@router.get("/{edition_date}", response_model=EditionOut)
async def get_edition(
    edition_date: date,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> EditionOut:
    # Read once: the same day decides both which answer a miss gets and how
    # long a hit may be cached, and a request that straddled UTC midnight
    # between two readings could call one date both future and past.
    #
    # The UTC day, not the local one: article timestamps are UTC, so between
    # local and UTC midnight the local calendar would call a day that is still
    # being ingested "past", and report a paper that is on its way as one that
    # will never exist.
    today = datetime.now(timezone.utc).date()
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)

    if edition is None:
        if edition_date >= today:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": NOT_PREPARED,
                    "message": "Bu günün baskısı henüz hazırlanmadı.",
                },
            )
        raise HTTPException(
            status_code=404,
            detail={"code": NOT_FOUND, "message": "Bu tarihe ait baskı yok."},
        )

    # A past day's edition is finished in practice: only POST /{date}/rebuild
    # rewrites one, and that is rare and deliberate. So it gets a long cache --
    # but a revalidating one, because "rare" is not "never" and an operator who
    # rebuilds yesterday has to be able to make readers see it. Today's can
    # still be assembled by the job (`daily-if-due` runs on every knock), so it
    # gets the short cache -- long enough to absorb a burst of readers, short
    # enough that the morning's first assembly is visible within the minute.
    if edition_date < today:
        archive_cache(response)
    else:
        public_cache(response, FRESH)
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
    dependencies=[Depends(require_admin)],
)
async def rebuild_edition(edition_date: date, db: AsyncSession = Depends(get_db)) -> EditionOut:
    """Reassemble one edition from scratch.

    Operator-only: assembling an edition is the most expensive thing this API
    can be asked to do, and it overwrites a published day. `python -m app.cli
    build-edition` is the same action from the shell.
    """
    await assemble_edition(db, edition_date)
    repo = EditionRepository(db)
    edition = await repo.get_by_date(edition_date)
    return _to_edition_out(edition)
