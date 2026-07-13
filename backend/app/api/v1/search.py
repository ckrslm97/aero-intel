from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.article import ArticleListOut, ArticleOut
from app.search.factory import get_search_backend

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=ArticleListOut)
async def search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    backend = get_search_backend(db)
    results = await backend.search(q, limit=limit)
    return ArticleListOut(total=len(results), items=[ArticleOut.model_validate(a) for a in results])
