import uuid
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, ARTICLES, public_cache
from app.core.db import get_db
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import ArticleListOut, ArticleOut

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ArticleListOut)
async def list_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    subcategory: str | None = None,
    region: str | None = None,
    airline: str | None = Query(
        None,
        max_length=6,
        description=(
            "IATA airline code; matches articles mentioning the airline. "
            "Special values: RIVALS (any main rival), ALL (any airline)"
        ),
    ),
    days: int | None = Query(
        None, ge=1, le=365, description="Only articles published within the last N days"
    ),
    date: date_type | None = Query(
        None, description="Only articles from this UTC day (archive view)"
    ),
    country: str | None = Query(
        None, max_length=80, description="Country name; matches articles mentioning it"
    ),
    airport: str | None = Query(
        None, max_length=4, description="Airport IATA code; the Hub Explorer's filter"
    ),
    translated_only: bool = Query(
        False, description="Only articles with a real Turkish translation -- Gazete's default"
    ),
    exclude_categories: list[str] | None = Query(
        None,
        description=(
            "Category slugs to leave out, repeated once per value. The Gazete "
            "drops safety/regulatory/sustainability/labor this way; every other "
            "caller (archive, search, hubs, the per-date edition) omits it and "
            "keeps full coverage. Nothing is deleted -- this is query-time only"
        ),
    ),
    min_importance: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Floor on the FOCUS-WEIGHTED importance score -- the Gazete's "
            "'fewer, more critical stories' filter. The compared value is "
            "enrichment.importance_score plus the category's editorial bonus "
            "(app.taxonomy.FOCUS_BONUS, the same weighting the daily edition's "
            "front page ranks by), NOT the raw column: raw importance rewards "
            "corroboration, so a flat floor on it culls single-sourced revenue "
            "management and events stories hardest -- the exact opposite of "
            "this desk's priority"
        ),
    ),
    response: Response = None,  # type: ignore[assignment]  -- FastAPI injects it
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    public_cache(response, ARTICLES)
    repo = ArticleRepository(db)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    items = await repo.list_recent(
        limit=limit, offset=offset, category=category, subcategory=subcategory,
        region=region, since=since, airline=airline, on_date=date,
        country=country, airport=airport, translated_only=translated_only,
        exclude_categories=exclude_categories, min_importance=min_importance,
    )
    # Filtered total (same clause as the list) so "load more" knows when to stop.
    # A short page IS the end of the result set, so the count query -- the more
    # expensive of the two, since it has no LIMIT to stop early -- is skipped
    # entirely for every filter that fits on one page.
    if len(items) < limit:
        total = offset + len(items)
    else:
        total = await repo.count(
            category=category, subcategory=subcategory, region=region, since=since,
            airline=airline, on_date=date, country=country, airport=airport,
            translated_only=translated_only, exclude_categories=exclude_categories,
            min_importance=min_importance,
        )
    return ArticleListOut(total=total, items=[ArticleOut.model_validate(a) for a in items])


@router.get("/counts")
async def article_counts(
    days: int | None = Query(None, ge=1, le=365),
    translated_only: bool = Query(
        False, description="Only articles with a real Turkish translation -- Gazete's default"
    ),
    exclude_categories: list[str] | None = Query(
        None, description="Category slugs to leave out -- mirrors the list endpoint"
    ),
    min_importance: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Focus-weighted importance floor -- mirrors the list endpoint, "
            "same FOCUS_BONUS weighting, so a badge counts what the list shows"
        ),
    ),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Article count per category, for the newspaper's tab badges.

    Takes the same filters as the list endpoint on purpose: a badge that counts
    rows the filtered list would never render is a badge that lies.
    """
    public_cache(response, AGGREGATES)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    return await ArticleRepository(db).count_by_category(
        since=since,
        translated_only=translated_only,
        exclude_categories=exclude_categories,
        min_importance=min_importance,
    )


@router.get("/daily-counts")
async def daily_counts(
    days: int = Query(7, ge=1, le=31),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Article count per UTC day, for the archive page's date strip."""
    public_cache(response, AGGREGATES)
    return await ArticleRepository(db).count_by_day(days=days)


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ArticleOut:
    repo = ArticleRepository(db)
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleOut.model_validate(article)
