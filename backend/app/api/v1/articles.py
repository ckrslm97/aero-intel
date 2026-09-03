import uuid
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, ARTICLES, public_cache
from app.core.db import get_db
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import (
    ArticleListOut,
    ArticleOut,
    ArticleSourceFacetOut,
    ArticleSourceOut,
)
from app.taxonomy import SOURCE_TIERS, effective_source_tier

router = APIRouter(prefix="/articles", tags=["articles"])

_TIER_DESCRIPTION = (
    "Source tier to keep, repeated once per value: "
    + " | ".join(SOURCE_TIERS)
    + ". Matches the EFFECTIVE tier -- a source with no declared tier falls "
    "back to its trust_weight bucket, exactly as the Risk Radarı resolves it. "
    "Omit for every tier, which is the default everywhere"
)


def _validated_tiers(tier: list[str] | None) -> list[str] | None:
    """Reject an unknown tier instead of quietly returning nothing.

    A typo'd `?tier=oficial` matches no source, so the honest answer is an
    empty page -- which is indistinguishable on screen from "no news today".
    422 says which value was wrong.
    """
    if not tier:
        return None
    unknown = [value for value in tier if value not in SOURCE_TIERS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown source tier(s): {', '.join(unknown)}. "
                f"Valid tiers: {', '.join(SOURCE_TIERS)}."
            ),
        )
    return list(tier)


def _window_start(hours: int | None, days: int | None, date: date_type | None):
    """The cutoff for whichever window the caller asked for.

    Compared against `coalesce(published_at, fetched_at)`, not against
    `published_at` alone -- see the `since` note at the top of
    app/repositories/article_repository.py for why, and note that this
    docstring naming the bare column is exactly the drift that note exists to
    prevent.

    `hours`, `days` and `date` are three ways to say the same thing and only
    one can be true at a time: a request carrying `hours=6&days=30` has no
    defensible answer (6 hours? 30 days? the intersection, which is just 6
    hours and makes `days` a lie?), so it is rejected rather than silently
    resolved. Callers pick one -- the Gazete's window chips send `hours` for
    the two short rungs and `days` for the rest; the archive sends `date`.
    """
    picked = [name for name, value in (("hours", hours), ("days", days), ("date", date)) if value]
    if len(picked) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"hours, days and date are mutually exclusive; got {', '.join(picked)}. "
                "Send exactly one time window."
            ),
        )
    now = datetime.now(timezone.utc)
    if hours:
        return now - timedelta(hours=hours)
    if days:
        return now - timedelta(days=days)
    return None


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
    hours: int | None = Query(
        None,
        ge=1,
        le=720,
        description=(
            "Only articles published within the last N hours -- the short end "
            "of the same axis as `days`, for the Gazete's 6s/24s window chips "
            "and its 'Son Dakika' strip. Mutually exclusive with days and date"
        ),
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
    min_intelligence: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Floor on the INTELLIGENCE score -- how much the story matters to "
            "a revenue-management desk (app/services/news_scoring.py). This is "
            "the filter the Gazete's 'fewer, more critical stories' control "
            "should use. Unlike `min_importance`, which floors "
            "importance_score + FOCUS_BONUS and is therefore a floor on the "
            "publisher's trust weight plus a per-CATEGORY constant, this scores "
            "each article on its own: recency, source, whether a rival or the "
            "home carrier is named and where, hub proximity, keyword relevance, "
            "and -- for the day's shortlist only -- the model's read on revenue, "
            "demand and capacity impact. Articles the scoring pass has never "
            "reached are EXCLUDED rather than treated as zero, so this can only "
            "ever narrow to rows the system has actually judged. Both filters "
            "may be sent together; they AND"
        ),
    ),
    tier: list[str] | None = Query(None, description=_TIER_DESCRIPTION),
    source: list[str] | None = Query(
        None,
        description=(
            "Outlet name to keep, repeated once per value, matched against "
            "Source.name exactly. One rung below `tier`: a tier says how "
            "authoritative, a name says which newsroom. The valid values for a "
            "given window are exactly what GET /articles/source-facets returns, "
            "so a chip built from that list can never send a name this misses. "
            "Omit for every outlet, which is the default everywhere"
        ),
    ),
    response: Response = None,  # type: ignore[assignment]  -- FastAPI injects it
    db: AsyncSession = Depends(get_db),
) -> ArticleListOut:
    public_cache(response, ARTICLES)
    repo = ArticleRepository(db)
    since = _window_start(hours, days, date)
    tiers = _validated_tiers(tier)
    items = await repo.list_recent(
        limit=limit, offset=offset, category=category, subcategory=subcategory,
        region=region, since=since, airline=airline, on_date=date,
        country=country, airport=airport, translated_only=translated_only,
        exclude_categories=exclude_categories, min_importance=min_importance,
        min_intelligence=min_intelligence, tiers=tiers, source_names=source,
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
            min_importance=min_importance, min_intelligence=min_intelligence,
            tiers=tiers, source_names=source,
        )
    return ArticleListOut(total=total, items=[ArticleOut.model_validate(a) for a in items])


@router.get("/counts")
async def article_counts(
    days: int | None = Query(None, ge=1, le=365),
    hours: int | None = Query(
        None,
        ge=1,
        le=720,
        description=(
            "Hour window -- mirrors the list endpoint, so a tab badge counts "
            "the same rows a 6s/24s view will render. Mutually exclusive "
            "with days"
        ),
    ),
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
    min_intelligence: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Intelligence-score floor -- mirrors the list endpoint, so a tab "
            "badge counts exactly the rows the filtered list will render. See "
            "the list endpoint for what the two floors each measure"
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
    since = _window_start(hours, days, None)
    return await ArticleRepository(db).count_by_category(
        since=since,
        translated_only=translated_only,
        exclude_categories=exclude_categories,
        min_importance=min_importance,
        min_intelligence=min_intelligence,
    )


#: How many outlets the facet endpoint will name. Ten is what the Gazete's chip
#: row shows before its "+N kaynak daha" expander, and thirty is roughly the
#: whole active source catalogue -- past that the list stops being a filter and
#: becomes a directory.
DEFAULT_SOURCE_FACET_LIMIT = 10
MAX_SOURCE_FACET_LIMIT = 30


@router.get("/source-facets", response_model=list[ArticleSourceFacetOut])
async def article_source_facets(
    limit: int = Query(
        DEFAULT_SOURCE_FACET_LIMIT,
        ge=1,
        le=MAX_SOURCE_FACET_LIMIT,
        description="How many outlets to name, busiest first",
    ),
    category: str | None = Query(None, description="Category slug -- mirrors the list endpoint"),
    days: int | None = Query(None, ge=1, le=365),
    hours: int | None = Query(None, ge=1, le=720),
    translated_only: bool = Query(
        False, description="Only articles with a real Turkish translation -- Gazete's default"
    ),
    exclude_categories: list[str] | None = Query(
        None, description="Category slugs to leave out -- mirrors the list endpoint"
    ),
    min_importance: float | None = Query(
        None, ge=0.0, le=1.0, description="Focus-weighted importance floor -- mirrors the list"
    ),
    min_intelligence: float | None = Query(
        None, ge=0.0, le=1.0, description="Intelligence-score floor -- mirrors the list"
    ),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[ArticleSourceFacetOut]:
    """Which outlets actually filled this window, with how many stories each.

    The options behind the Gazete's "Kaynak" chip row. Server-side because the
    list is paginated: deriving the chips from the thirty rows on screen would
    describe page 1 rather than the window, and the counts would move as the
    reader paged.

    Takes the same window/category/quality filters as the list so a chip
    counting rows the filtered list would not render cannot exist. It
    deliberately does NOT take `tier` or `source`: these are the options the
    reader chooses *from*, and narrowing them by the current selection would
    make every chip but the active one disappear the moment one was pressed.
    """
    public_cache(response, AGGREGATES)
    since = _window_start(hours, days, None)
    rows = await ArticleRepository(db).count_by_source(
        limit=limit,
        since=since,
        category=category,
        translated_only=translated_only,
        exclude_categories=exclude_categories,
        min_importance=min_importance,
        min_intelligence=min_intelligence,
    )
    return [
        ArticleSourceFacetOut(name=name, tier=tier, count=count) for name, tier, count in rows
    ]


@router.get("/daily-counts")
async def daily_counts(
    days: int = Query(7, ge=1, le=31),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Article count per UTC day, for the archive page's date strip."""
    public_cache(response, AGGREGATES)
    return await ArticleRepository(db).count_by_day(days=days)


@router.get("/{article_id}/sources", response_model=list[ArticleSourceOut])
async def article_sources(
    article_id: uuid.UUID,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[ArticleSourceOut]:
    """Every outlet that ran this story, oldest first.

    The list behind `corroborating_source_count`. That number has been on the
    Gazete's analysis drawer since it shipped and has never been checkable: the
    duplicate group it counts is stored (Article.duplicate_of_id) but was never
    exposed, so "3 kaynak" was a claim the reader had to take on faith.

    Lazy on purpose -- one request per article a reader actually opens, not a
    join riding along with every one of the thirty rows they scroll past.

    404 rather than an empty list for an unknown id: an article with no
    duplicates still returns exactly one row (itself), so `[]` can only mean
    the id is wrong, and answering it with a valid-looking empty answer would
    render as "no sources corroborated this".
    """
    public_cache(response, ARTICLES)
    repo = ArticleRepository(db)
    group = await repo.list_duplicate_group(article_id)
    if not group:
        raise HTTPException(status_code=404, detail="Article not found")
    return [
        ArticleSourceOut(
            source_name=article.source.name,
            source_tier=effective_source_tier(
                article.source.tier, article.source.trust_weight
            ),
            trust_weight=article.source.trust_weight,
            url=article.url,
            published_at=article.published_at,
            title=article.title,
            is_primary=article.id == article_id,
        )
        for article in group
    ]


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ArticleOut:
    repo = ArticleRepository(db)
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleOut.model_validate(article)
