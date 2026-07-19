from fastapi import APIRouter, Response

from app.api.cache_headers import STATIC, public_cache
from app.taxonomy import CATEGORIES, GENERAL_CATEGORY

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
