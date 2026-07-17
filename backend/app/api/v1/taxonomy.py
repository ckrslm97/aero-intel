from fastapi import APIRouter

from app.taxonomy import CATEGORIES, GENERAL_CATEGORY

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("")
async def get_taxonomy() -> list[dict]:
    """Category/subcategory slugs only -- Turkish labels, colors, and icons are
    owned by the frontend (frontend/src/lib/taxonomy.ts). This just lets the
    frontend confirm it hasn't drifted from the backend's taxonomy.
    """
    return [
        {"slug": c.slug, "subcategories": [s.slug for s in c.subcategories]} for c in CATEGORIES
    ] + [{"slug": GENERAL_CATEGORY, "subcategories": []}]
