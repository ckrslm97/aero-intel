import uuid
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

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
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    repo = ArticleRepository(db)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    items = await repo.list_recent(
        limit=limit, offset=offset, category=category, subcategory=subcategory,
        region=region, since=since, airline=airline, on_date=date,
    )
    # Filtered total (same clause as the list) so "load more" knows when to stop.
    total = await repo.count(
        category=category, subcategory=subcategory, region=region, since=since,
        airline=airline, on_date=date,
    )
    return ArticleListOut(total=total, items=[ArticleOut.model_validate(a) for a in items])


@router.get("/counts")
async def article_counts(
    days: int | None = Query(None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Article count per category, for the newspaper's tab badges."""
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    return await ArticleRepository(db).count_by_category(since=since)


@router.get("/daily-counts")
async def daily_counts(
    days: int = Query(7, ge=1, le=31),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Article count per UTC day, for the archive page's date strip."""
    return await ArticleRepository(db).count_by_day(days=days)


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ArticleOut:
    repo = ArticleRepository(db)
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleOut.model_validate(article)
