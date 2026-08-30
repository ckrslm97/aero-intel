"""The airline campaign timeline behind the /kampanyalar page and the calendar's
campaign ribbons.

Shape of this module (PR7)
--------------------------
`GET /promotions` still returns a **bare list**, exactly as it did before. Two
clients read it -- the campaign page and the events calendar's ribbon overlay --
and wrapping the payload in `{items, total}` would have broken both for the sake
of one number. So the total lives in its own tiny endpoint, `GET
/promotions/count`, which takes the identical filter set and is computed by the
identical code path (`_matching_promotions`), so the two can never disagree
about what "matching" means. Pagination is opt-in: no `limit` means the whole
filtered window, which is what both existing clients pass today.

Where each filter is applied, and why it is split
-------------------------------------------------
Everything that is a plain column -- carrier, dates, campaign_type,
business_class, discount, confidence band, review flag -- filters in SQL.
Three do not:

* **status** is computed, never stored (see services/campaign_status.py). There
  is no column to filter on, and re-deriving the decision table in SQL would
  give us two implementations of the one rule the whole feature rests on.
* **country** and **region** live in three places at once: the flat `region`
  column, `markets_json`, and `route_json`. A JSONB query per shape would be
  three `@>` clauses and still miss the flat column.

All three are therefore applied in Python, over a result set that is already
bounded by the SQL filters (the page fetches an eight-week window, ~hundreds of
rows). Because `limit`/`offset` slice *after* that pass, a page is always a page
of genuinely matching rows -- slicing in SQL first would have handed back short
pages with no way to tell a filtered-out row from a missing one.
"""
import csv
import io
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import Date, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import FRESH, public_cache
from app.core.db import get_db
from app.core.tr_dates import format_optional_range
from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import NEW_WINDOW_HOURS, Promotion
from app.services.campaign_status import campaign_status

router = APIRouter(prefix="/promotions", tags=["promotions"])

#: Hard ceiling on an export. Vercel's function limit is 30s and the whole
#: response is built in memory before the first chunk leaves; 2000 rows of
#: 23 columns is comfortably inside both. An export that hits the cap is
#: truncated rather than failing -- a partial CSV is still usable, a timeout
#: is not -- and the response says so in a header.
EXPORT_ROW_CAP = 2000


# Faz 15 contract fix: neither endpoint below filtered on this at all, so a
# row pipeline_v2's build_promotion() writes at the low band (or Faz 13's
# mark_legacy_campaigns_superseded() marks superseded) would still have shown
# up here once pipeline_v2 is on -- the "K8 rows stop being served" claim was
# only true of the confidence system, not of this read path. NULL is
# deliberately allowed through: every scraped Pegasus row (promo_scrape.py)
# has never been scored by the new system at all, and treating "never
# assessed" the same as "assessed and found wanting" would empty the live
# page of everything it serves today.
def _publishable_promotions():
    return and_(
        Promotion.superseded_at.is_(None),
        or_(
            Promotion.confidence_band.is_(None),
            Promotion.confidence_band.in_(("high", "medium")),
        ),
    )


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    airline_code: str
    airline_name: str
    title_tr: str
    summary_tr: str
    discount_pct: int | None
    markets: str | None
    sale_starts: date | None
    sale_ends: date | None
    travel_starts: date | None
    travel_ends: date | None
    url: str
    source_name: str
    region: str | None
    detected_at: datetime

    # --- campaign intelligence (PR1-PR5 columns, first exposed here) --------
    #
    # Every one of these is NULL on a legacy row and stays NULL: the analyst
    # table renders "—" for an unclassified campaign rather than guessing a
    # type for it. Nothing below is required to render the page.
    campaign_type: str | None = None
    business_class: str | None = None
    route_scope: str | None = None
    ond: str | None = None
    origin_code: str | None = None
    dest_code: str | None = None
    route_json: dict | None = None
    confidence_score: float | None = None
    confidence_band: str | None = None
    review_required: bool | None = None
    conflict_detected: bool | None = None
    classification_reason: str | None = None
    first_seen_at: datetime | None = None
    last_changed_at: datetime | None = None
    attrs_json: dict | None = None
    evidence_json: dict | None = None
    date_flags_json: dict | None = None

    #: How many recorded edits this campaign has, and how many pages told us
    #: about it. Filled in by `_serialize` with two grouped queries per page --
    #: never a relationship load, which would be one query per row.
    version_count: int = 0
    source_count: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        """UPCOMING / ACTIVE_BOOKING / BOOKING_CLOSED_TRAVEL_ACTIVE / EXPIRED /
        UNKNOWN, derived here rather than stored -- see
        services/campaign_status.py for why a status column would be wrong
        every morning."""
        return campaign_status(
            self.sale_starts,
            self.sale_ends,
            self.travel_starts,
            self.travel_ends,
            _today(),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sale_range_tr(self) -> str:
        """Pre-formatted Turkish range so the frontend never re-implements
        month names -- the same contract as EventOut.date_range_tr, but through
        `format_optional_range` because every date here is nullable and a
        half-known window has to say which half is missing."""
        return format_optional_range(self.sale_starts, self.sale_ends)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def travel_range_tr(self) -> str:
        return format_optional_range(self.travel_starts, self.travel_ends)


class PromotionVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    #: {field: {"previous": ..., "new": ..., "conflict"?: bool, "rejected"?: ...}}
    changed_fields: dict
    source_url: str | None
    created_at: datetime


class PromotionSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    source_name: str | None
    #: official | newsroom | secondary -- the conflict-resolution ordering.
    source_tier: str | None
    source_quality: float | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None


def _today() -> date:
    """UTC, and a whole day. Status buckets must not move because a cron ran
    at 23:40 local."""
    return datetime.now(timezone.utc).date()


# --- filters --------------------------------------------------------------


@dataclass(frozen=True)
class _Filters:
    """One filter set, shared by /promotions, /promotions/count and
    /promotions/export so all three agree on what "matching" means."""

    airline: Sequence[str] = field(default_factory=tuple)
    date_from: date | None = None
    date_to: date | None = None
    days: int | None = None
    campaign_type: Sequence[str] = field(default_factory=tuple)
    business_class: Sequence[str] = field(default_factory=tuple)
    status: Sequence[str] = field(default_factory=tuple)
    country: str | None = None
    region: Sequence[str] = field(default_factory=tuple)
    min_discount: int | None = None
    band: Sequence[str] = field(default_factory=tuple)
    review_required: bool | None = None


def _apply_sql_filters(query, f: _Filters):
    if f.airline:
        query = query.where(Promotion.airline_code.in_(f.airline))

    # Every date filter below has to survive nulls, because every date column
    # is nullable. The three cases match exactly what the timeline draws:
    #   dated window  -> a bar, filtered on its real edges;
    #   open-ended    -> a bar that fades out; it is still running, so it
    #                    reaches any date_from;
    #   no start date -> a point marker at detected_at, filtered on that.
    if f.date_from:
        query = query.where(
            or_(
                Promotion.sale_ends >= f.date_from,
                and_(Promotion.sale_ends.is_(None), Promotion.sale_starts.isnot(None)),
                and_(
                    Promotion.sale_starts.is_(None),
                    cast(Promotion.detected_at, Date) >= f.date_from,
                ),
            )
        )
    if f.date_to:
        query = query.where(
            or_(
                Promotion.sale_starts <= f.date_to,
                and_(
                    Promotion.sale_starts.is_(None),
                    cast(Promotion.detected_at, Date) <= f.date_to,
                ),
            )
        )
    if f.days:
        query = query.where(
            Promotion.detected_at >= datetime.now(timezone.utc) - timedelta(days=f.days)
        )

    if f.campaign_type:
        query = query.where(Promotion.campaign_type.in_(f.campaign_type))
    if f.business_class:
        query = query.where(Promotion.business_class.in_(f.business_class))
    if f.min_discount is not None:
        # A campaign with no stated rate is excluded on purpose: "at least 30%"
        # is a claim, and an unknown rate cannot support it.
        query = query.where(Promotion.discount_pct >= f.min_discount)
    if f.band:
        query = query.where(Promotion.confidence_band.in_(f.band))
    if f.review_required is True:
        query = query.where(Promotion.review_required.is_(True))
    elif f.review_required is False:
        # NULL means "never queued for review" (every legacy row), which is
        # the same thing to a reader asking for the non-flagged set.
        query = query.where(
            or_(Promotion.review_required.is_(False), Promotion.review_required.is_(None))
        )
    return query


def _norm(value: object) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _countries_of(row: Promotion) -> set[str]:
    """Every country this campaign names, from either structured column."""
    found: set[str] = set()
    markets = row.markets_json or {}
    if isinstance(markets, dict):
        for name in markets.get("countries") or []:
            found.add(_norm(name))
    route = row.route_json or {}
    if isinstance(route, dict):
        for side in ("origin", "dest"):
            leg = route.get(side)
            if isinstance(leg, dict) and leg.get("country"):
                found.add(_norm(leg["country"]))
    found.discard("")
    return found


def _regions_of(row: Promotion) -> set[str]:
    """The flat column plus both JSON shapes. A campaign filed under
    `region="europe"` and one whose route resolves into Europe are the same
    answer to "show me Europe"."""
    found: set[str] = {_norm(row.region)}
    markets = row.markets_json or {}
    if isinstance(markets, dict):
        for slug in markets.get("regions") or []:
            found.add(_norm(slug))
    route = row.route_json or {}
    if isinstance(route, dict):
        for side in ("origin", "dest"):
            leg = route.get(side)
            if isinstance(leg, dict) and leg.get("region"):
                found.add(_norm(leg["region"]))
    found.discard("")
    return found


def _passes_python_filters(row: Promotion, f: _Filters, today: date) -> bool:
    if f.status:
        computed = campaign_status(
            row.sale_starts, row.sale_ends, row.travel_starts, row.travel_ends, today
        )
        if computed not in f.status:
            return False
    if f.country and _norm(f.country) not in _countries_of(row):
        return False
    if f.region and not ({_norm(r) for r in f.region} & _regions_of(row)):
        return False
    return True


async def _matching_promotions(db: AsyncSession, f: _Filters) -> list[Promotion]:
    """Every publishable row matching `f`, newest sighting first, unpaginated.

    The single definition of "matching" -- list, count and export all call it,
    which is what makes `count` a promise about the list rather than a second
    opinion.
    """
    query = (
        select(Promotion)
        .where(_publishable_promotions())
        # Newest sighting first: this endpoint's headline job is "what just
        # launched", and the timeline re-sorts into lanes client-side anyway.
        .order_by(Promotion.detected_at.desc())
    )
    rows = (await db.execute(_apply_sql_filters(query, f))).scalars().all()
    today = _today()
    return [row for row in rows if _passes_python_filters(row, f, today)]


async def _serialize(db: AsyncSession, rows: Sequence[Promotion]) -> list[PromotionOut]:
    """Rows -> PromotionOut, with the two child-table counts attached.

    Two grouped queries for the whole page, not one per row: a relationship
    load here would be an N+1 on the page's hottest endpoint.
    """
    ids = [row.id for row in rows]
    versions: dict[uuid.UUID, int] = {}
    sources: dict[uuid.UUID, int] = {}
    if ids:
        versions = dict(
            (
                await db.execute(
                    select(CampaignVersion.promotion_id, func.count())
                    .where(CampaignVersion.promotion_id.in_(ids))
                    .group_by(CampaignVersion.promotion_id)
                )
            ).all()
        )
        sources = dict(
            (
                await db.execute(
                    select(CampaignSource.promotion_id, func.count())
                    .where(CampaignSource.promotion_id.in_(ids))
                    .group_by(CampaignSource.promotion_id)
                )
            ).all()
        )
    return [
        PromotionOut.model_validate(row).model_copy(
            update={
                "version_count": versions.get(row.id, 0),
                "source_count": sources.get(row.id, 0),
            }
        )
        for row in rows
    ]


# --- shared query-parameter declarations ----------------------------------
#
# Annotated aliases rather than `= Query(...)` defaults, and rather than one
# Depends() filter object. Annotated keeps the *Python* default a plain None,
# which matters because these endpoints are called directly (never over HTTP)
# by the test suite: with `= Query(None)` an unpassed argument arrives as a
# fastapi.params.Query instance, and `tuple(that)` raises. A Depends() object
# would fix that too, at the cost of making every existing caller construct a
# container to pass six Nones.

AirlineParam = Annotated[
    list[str] | None,
    # Multi-select, same convention as /recommendations: `?airline=PC&airline=TK`
    # widens to either. An absent or empty list means "every carrier".
    Query(description="IATA airline codes, e.g. PC"),
]
DateFromParam = Annotated[
    date | None,
    Query(description="Only campaigns whose sale window reaches this date or later"),
]
DateToParam = Annotated[
    date | None,
    Query(description="Only campaigns whose sale window starts on/before this date"),
]
DaysParam = Annotated[
    int | None,
    Query(
        ge=1,
        le=365,
        description="Only campaigns DETECTED in the last N days (freshness, not sale window)",
    ),
]
CampaignTypeParam = Annotated[
    list[str] | None, Query(description="app/taxonomy.py CAMPAIGN_TYPES values, repeatable")
]
BusinessClassParam = Annotated[
    list[str] | None, Query(description="CAMPAIGN_BUSINESS_CLASSES values, repeatable")
]
StatusParam = Annotated[
    list[str] | None,
    Query(description="CAMPAIGN_STATUSES values, repeatable (computed at read time)"),
]
CountryParam = Annotated[
    str | None, Query(description="Country named in markets_json or resolved in route_json")
]
RegionParam = Annotated[list[str] | None, Query(description="World-region slugs, repeatable")]
MinDiscountParam = Annotated[
    int | None, Query(ge=1, le=100, description="Minimum stated discount percentage")
]
BandParam = Annotated[list[str] | None, Query(description="Confidence bands: high | medium")]
ReviewRequiredParam = Annotated[
    bool | None, Query(description="Only the review queue (true) or only clean rows (false)")
]


def _filters(
    airline: list[str] | None,
    date_from: date | None,
    date_to: date | None,
    days: int | None,
    campaign_type: list[str] | None,
    business_class: list[str] | None,
    status: list[str] | None,
    country: str | None,
    region: list[str] | None,
    min_discount: int | None,
    band: list[str] | None,
    review_required: bool | None,
) -> _Filters:
    return _Filters(
        airline=tuple(airline or ()),
        date_from=date_from,
        date_to=date_to,
        days=days,
        campaign_type=tuple(campaign_type or ()),
        business_class=tuple(business_class or ()),
        status=tuple(status or ()),
        country=country,
        region=tuple(region or ()),
        min_discount=min_discount,
        band=tuple(band or ()),
        review_required=review_required,
    )


@router.get("", response_model=list[PromotionOut])
async def list_promotions(
    airline: AirlineParam = None,
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    days: DaysParam = None,
    campaign_type: CampaignTypeParam = None,
    business_class: BusinessClassParam = None,
    status: StatusParam = None,
    country: CountryParam = None,
    region: RegionParam = None,
    min_discount: MinDiscountParam = None,
    band: BandParam = None,
    review_required: ReviewRequiredParam = None,
    # Opt-in: no limit means the whole filtered window, which is what the
    # campaign page and the calendar overlay both ask for.
    limit: Annotated[int | None, Query(ge=1, le=EXPORT_ROW_CAP)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[PromotionOut]:
    public_cache(response, FRESH)
    rows = await _matching_promotions(
        db,
        _filters(
            airline, date_from, date_to, days, campaign_type, business_class,
            status, country, region, min_discount, band, review_required,
        ),
    )
    page = rows[offset : offset + limit] if limit is not None else rows[offset:]
    return await _serialize(db, page)


@router.get("/count")
async def count_promotions(
    airline: AirlineParam = None,
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    days: DaysParam = None,
    campaign_type: CampaignTypeParam = None,
    business_class: BusinessClassParam = None,
    status: StatusParam = None,
    country: CountryParam = None,
    region: RegionParam = None,
    min_discount: MinDiscountParam = None,
    band: BandParam = None,
    review_required: ReviewRequiredParam = None,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """How many rows `GET /promotions` would return for the same filters.

    Its own endpoint rather than an envelope or an X-Total-Count header on the
    list: the list's payload shape is a published contract with two clients,
    and a header would be invisible to `apiFetch`, which only ever reads the
    body.
    """
    public_cache(response, FRESH)
    rows = await _matching_promotions(
        db,
        _filters(
            airline, date_from, date_to, days, campaign_type, business_class,
            status, country, region, min_discount, band, review_required,
        ),
    )
    return {"total": len(rows)}


@router.get("/new-count")
async def count_new_promotions(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """How many campaigns we first saw in the last 48 hours.

    Its own endpoint so the "Son 48 saatte N yeni kampanya" banner is a number
    over the whole table, not a count of whatever happened to fall inside the
    timeline's eight-week window.
    """
    public_cache(response, FRESH)
    return await new_promotion_counts(db)


async def new_promotion_counts(db: AsyncSession) -> dict:
    """The count itself, split out from the endpoint so a second caller reuses
    it instead of restating the window and the publishability clause.

    Kokpit's "Rakip Aktivitesi" signal tile is that caller (see
    app/services/cockpit_signals_service.py): it prints the same number the
    /kampanyalar banner does, and a hand-rolled second query would eventually
    drift from `_publishable_promotions()` and show a count the campaign page
    could not reproduce.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEW_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(Promotion.airline_code).where(
                Promotion.detected_at >= cutoff, _publishable_promotions()
            )
        )
    ).scalars().all()
    return {
        "window_hours": NEW_WINDOW_HOURS,
        "count": len(rows),
        "airline_codes": sorted(set(rows)),
    }


# --- export ---------------------------------------------------------------

#: English snake_case, deliberately. This file is an analyst's hand-off into
#: Excel/pandas/BI, not a page: column names get typed into formulas and
#: `df["sale_ends"]`, where a Turkish header with an "ı" in it is a liability.
#: The Turkish is in the UI, where a person reads it.
EXPORT_COLUMNS = (
    "carrier",
    "campaign_name",
    "campaign_type",
    "business_class",
    "status",
    "booking_start",
    "booking_end",
    "travel_start",
    "travel_end",
    "origin",
    "destination",
    "ond",
    "route_scope",
    "discount_pct",
    "currency",
    "price_floor",
    "promo_code",
    "source_url",
    "confidence_score",
    "confidence_band",
    "detected_at",
    "first_seen_at",
    "last_changed_at",
)


def _attr(row: Promotion, key: str) -> str:
    attrs = row.attrs_json or {}
    value = attrs.get(key) if isinstance(attrs, dict) else None
    return "" if value is None else str(value)


def _iso(value: date | datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _export_row(row: Promotion, today: date) -> list[str]:
    return [
        row.airline_code,
        row.title_tr,
        row.campaign_type or "",
        row.business_class or "",
        campaign_status(
            row.sale_starts, row.sale_ends, row.travel_starts, row.travel_ends, today
        ),
        _iso(row.sale_starts),
        _iso(row.sale_ends),
        _iso(row.travel_starts),
        _iso(row.travel_ends),
        row.origin_code or "",
        row.dest_code or "",
        row.ond or "",
        row.route_scope or "",
        "" if row.discount_pct is None else str(row.discount_pct),
        _attr(row, "currency"),
        _attr(row, "price_floor"),
        _attr(row, "promo_code"),
        row.url,
        "" if row.confidence_score is None else f"{row.confidence_score:.3f}",
        row.confidence_band or "",
        _iso(row.detected_at),
        _iso(row.first_seen_at),
        _iso(row.last_changed_at),
    ]


def _csv_lines(rows: Sequence[Promotion], today: date) -> Iterator[str]:
    """One `csv.writer` over a rewound buffer per row, so the response streams
    instead of being assembled as one string -- the row cap protects the
    30s function limit, this protects the memory ceiling under it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    def flush() -> str:
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return chunk

    writer.writerow(EXPORT_COLUMNS)
    yield flush()
    for row in rows:
        writer.writerow(_export_row(row, today))
        yield flush()


@router.get("/export")
async def export_promotions(
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv",
    airline: AirlineParam = None,
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    days: DaysParam = None,
    campaign_type: CampaignTypeParam = None,
    business_class: BusinessClassParam = None,
    status: StatusParam = None,
    country: CountryParam = None,
    region: RegionParam = None,
    min_discount: MinDiscountParam = None,
    band: BandParam = None,
    review_required: ReviewRequiredParam = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The filtered set as a download: `format=csv` for a spreadsheet,
    `format=json` for the same rows the API serves.

    Capped at EXPORT_ROW_CAP rows. `X-Row-Cap-Reached` says whether the cap
    actually bit, so a script can narrow its filters instead of silently
    analysing a truncated table.
    """
    rows = await _matching_promotions(
        db,
        _filters(
            airline, date_from, date_to, days, campaign_type, business_class,
            status, country, region, min_discount, band, review_required,
        ),
    )
    truncated = len(rows) > EXPORT_ROW_CAP
    rows = rows[:EXPORT_ROW_CAP]
    stamp = _today().isoformat()
    headers = {
        "Content-Disposition": f'attachment; filename="aerointel-kampanyalar-{stamp}.{format}"',
        "X-Row-Cap-Reached": "true" if truncated else "false",
    }

    if format == "json":
        payload = [item.model_dump(mode="json") for item in await _serialize(db, rows)]
        response: Response = JSONResponse(content=payload, headers=headers)
    else:
        response = StreamingResponse(
            _csv_lines(rows, _today()), media_type="text/csv; charset=utf-8", headers=headers
        )
    public_cache(response, FRESH)
    return response


# --- one campaign's history and provenance --------------------------------


async def _require_promotion(db: AsyncSession, promotion_id: uuid.UUID) -> Promotion:
    row = await db.get(Promotion, promotion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Kampanya bulunamadı")
    return row


@router.get("/{promotion_id}/versions", response_model=list[PromotionVersionOut])
async def list_promotion_versions(
    promotion_id: uuid.UUID,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[PromotionVersionOut]:
    """What changed on this campaign, newest edit first.

    Fetched lazily by the drawer rather than ridden along with every row on the
    list: most campaigns have no versions at all, and the ones that do are read
    one at a time.
    """
    public_cache(response, FRESH)
    await _require_promotion(db, promotion_id)
    rows = (
        await db.execute(
            select(CampaignVersion)
            .where(CampaignVersion.promotion_id == promotion_id)
            .order_by(CampaignVersion.version_no.desc())
        )
    ).scalars().all()
    return [PromotionVersionOut.model_validate(row) for row in rows]


@router.get("/{promotion_id}/sources", response_model=list[PromotionSourceOut])
async def list_promotion_sources(
    promotion_id: uuid.UUID,
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[PromotionSourceOut]:
    """Every page that told us about this campaign, most official first --
    which is also the order the conflict resolver used to pick a winner."""
    public_cache(response, FRESH)
    await _require_promotion(db, promotion_id)
    rows = (
        await db.execute(
            select(CampaignSource)
            .where(CampaignSource.promotion_id == promotion_id)
            .order_by(CampaignSource.first_seen_at.asc().nulls_last(), CampaignSource.url)
        )
    ).scalars().all()
    tier_rank = {"official": 0, "newsroom": 1, "secondary": 2}
    rows = sorted(rows, key=lambda s: tier_rank.get(s.source_tier or "", 3))
    return [PromotionSourceOut.model_validate(row) for row in rows]
