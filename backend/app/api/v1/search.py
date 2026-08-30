from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.article import ArticleListOut, ArticleOut
from app.search.factory import get_search_backend
from app.taxonomy import CATEGORY_SLUGS

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=ArticleListOut)
async def search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = Query(
        None,
        description=f"Restrict results to one category slug: {', '.join(CATEGORY_SLUGS)}",
    ),
    days: int | None = Query(
        None,
        ge=1,
        le=365,
        description=(
            "Only articles published (or, lacking a publication date, fetched) "
            "within the last N days"
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    """Full-text search.

    `total` is a real count of the matching rows, not the size of the page
    being returned -- it used to be the latter, so every search with more hits
    than the limit reported exactly the limit and the result count was a
    restatement of the page size.

    Turkish caveat, inherited from the index: the vector is built with
    Postgres's `english` configuration (see app/pipeline/search_indexing.py),
    which now includes the Turkish headline and summary but does not stem them.
    Turkish words match verbatim -- "yakıt" finds "yakıt", not "yakıtın".
    """
    # Checked here rather than declared as an enum on the Query: FastAPI's
    # `enum=` is OpenAPI documentation, not validation, so a typo'd slug would
    # sail through and return an empty page -- which reads as "nothing matched
    # your search" instead of "that category does not exist".
    if category is not None and category not in CATEGORY_SLUGS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown category: {category}. "
                f"Valid categories: {', '.join(CATEGORY_SLUGS)}."
            ),
        )
    backend = get_search_backend(db)
    results = await backend.search(q, limit=limit, category=category, days=days)
    # A short page IS the whole result set, so the count query -- the more
    # expensive of the two, having no LIMIT to stop early -- is skipped for
    # every search that fits on one page. Same reasoning as GET /articles.
    total = (
        len(results)
        if len(results) < limit
        else await backend.count(q, category=category, days=days)
    )
    return ArticleListOut(total=total, items=[ArticleOut.model_validate(a) for a in results])
