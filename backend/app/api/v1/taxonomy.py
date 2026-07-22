from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, STATIC, public_cache
from app.core.db import get_db
from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.taxonomy import CATEGORIES, COUNTRY_TO_REGION, GENERAL_CATEGORY

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("")
async def get_taxonomy(response: Response = None) -> list[dict]:  # type: ignore[assignment]
    """Category/subcategory slugs only -- Turkish labels, colors, and icons are
    owned by the frontend (frontend/src/lib/taxonomy.ts). This just lets the
    frontend confirm it hasn't drifted from the backend's taxonomy.
    """
    # Python constants: they can only change on a deploy.
    public_cache(response, STATIC)
    return [
        {"slug": c.slug, "subcategories": [s.slug for s in c.subcategories]} for c in CATEGORIES
    ] + [{"slug": GENERAL_CATEGORY, "subcategories": []}]


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
