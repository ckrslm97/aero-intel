"""Country coverage for the archive filters.

The slug-listing endpoint that used to sit here existed so the frontend could
check it had not drifted from app/taxonomy.py. Checking at runtime was always
the weak version of that idea -- nothing acted on a mismatch. The frontend's
taxonomy is now generated from the backend's (scripts/export_taxonomy.py) and
CI fails when it is stale, so drift is caught before it ships.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.taxonomy import COUNTRY_TO_REGION

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/countries")
async def get_countries(
    days: int = Query(90, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Countries the archive can actually filter by, with their coverage.

    Counted rather than listed. The gazetteer knows 51 country names, but a
    dropdown offering all of them is mostly dead options -- the user picks a
    country, gets an empty page, and learns not to trust the control. Only
    countries with at least one article are returned, busiest first.
    """
    public_cache(response, AGGREGATES)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Entity.name, func.count(func.distinct(Article.id)))
        .select_from(Entity)
        .join(ArticleEntity, ArticleEntity.entity_id == Entity.id)
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(
            Entity.entity_type == "country",
            Article.is_duplicate.is_(False),
            func.coalesce(Article.published_at, Article.fetched_at) >= since,
        )
        .group_by(Entity.name)
        .order_by(func.count(func.distinct(Article.id)).desc(), Entity.name)
    )
    return [
        {
            "name": name,
            "article_count": count,
            # The region the country belongs to, so the dropdown can group.
            "region": COUNTRY_TO_REGION.get(name.lower()),
        }
        for name, count in result.all()
    ]
