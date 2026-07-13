import uuid

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
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    repo = ArticleRepository(db)
    items = await repo.list_recent(limit=limit, offset=offset, category=category)
    total = await repo.count()
    return ArticleListOut(total=total, items=[ArticleOut.model_validate(a) for a in items])


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ArticleOut:
    repo = ArticleRepository(db)
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleOut.model_validate(article)
