"""Excel-style pivot aggregation over the news archive.

The /analiz page lets the user assign any dimension to rows, any other to
columns, and pick a measure -- so the shape of the query is chosen at runtime.
Two rules keep that safe and correct:

1. Nothing the user sends is ever interpolated into SQL. `rows`, `cols`,
   `measure` and the filter keys are looked up in the DIMENSIONS / MEASURES
   whitelists below; an unknown slug raises ValueError (the API turns that into
   a 400). Filter *values* travel as bound parameters as usual.

2. It is ONE query. Row totals, column totals and the grand total come from
   `GROUP BY CUBE(row, col)` rather than from summing the cells in Python,
   because two of the measures are not additive: `sources` is a
   COUNT(DISTINCT) (the same source feeds many cells, so summing double-counts
   it) and the averages are averages. CUBE makes Postgres compute each total
   over the real underlying rows. GROUPING() tells a NULL that means "totalled
   away" apart from a NULL that is genuinely the dimension's value.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.taxonomy import RIVAL_CODES

# Shown for rows whose dimension value is NULL (an article with no detected
# region, an un-enriched article, a story mentioning no airline).
NULL_LABEL = "(belirtilmemiş)"
CELL_SEPARATOR = "|"

# A pivot the browser can actually render. Anything beyond this is noise in a
# table; the response flags `truncated` so the UI can say so.
MAX_ROWS = 100
MAX_COLS = 40

DEFAULT_DAYS = 30

# Same fallback the archive uses: feeds that omit dates still belong to a day.
_DAY_EXPR = func.coalesce(Article.published_at, Article.fetched_at)


def _period(unit: str, fmt: str):
    """A day/week/month bucket as text.

    timezone('UTC', ...) first -- date_trunc on a bare timestamptz truncates in
    the *session* timezone, which would move late-evening UTC articles into the
    neighbouring day on any non-UTC deployment.
    """
    return func.to_char(func.date_trunc(unit, func.timezone("UTC", _DAY_EXPR)), fmt)


def _airline_source():
    """Airline mentions as a pre-filtered subquery to LEFT JOIN against.

    Joining article_entities directly would multiply every article by its
    country/airport/aircraft entities too, so an article mentioning three
    countries and one airline would produce three phantom "(belirtilmemiş)"
    rows. Filtering entity_type inside the subquery keeps exactly one row per
    (article, airline) pair -- an article naming two carriers deliberately
    counts under both, which is what a pivot by airline means.
    """
    return (
        select(
            ArticleEntity.article_id.label("article_id"),
            func.coalesce(Entity.code, Entity.name).label("airline"),
        )
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(Entity.entity_type == "airline")
        .subquery()
    )


@dataclass(frozen=True)
class Dimension:
    label: str
    build: Callable[[Any], Any]
    needs: tuple[str, ...] = ()
    # Time buckets read in calendar order; everything else is ranked by size.
    chronological: bool = False


@dataclass(frozen=True)
class Measure:
    label: str
    build: Callable[[], Any]
    decimals: int | None = None  # None -> whole number
    needs: tuple[str, ...] = field(default=())


DIMENSIONS: dict[str, Dimension] = {
    "category": Dimension("Kategori", lambda _: ArticleEnrichment.category, ("enrichment",)),
    "subcategory": Dimension(
        "Alt kategori", lambda _: ArticleEnrichment.subcategory, ("enrichment",)
    ),
    "region": Dimension("Bölge", lambda _: ArticleEnrichment.region, ("enrichment",)),
    "sentiment": Dimension("Duygu", lambda _: ArticleEnrichment.sentiment, ("enrichment",)),
    "translated": Dimension(
        "Çeviri durumu",
        lambda _: case(
            (ArticleEnrichment.translated_at.is_not(None), "Çevrildi"),
            else_="Çevrilmedi",
        ),
        ("enrichment",),
    ),
    "source": Dimension("Kaynak", lambda _: Source.name, ("source",)),
    "airline": Dimension("Havayolu", lambda sub: sub.c.airline, ("airline",)),
    "day": Dimension("Gün", lambda _: _period("day", "YYYY-MM-DD"), chronological=True),
    "week": Dimension("Hafta", lambda _: _period("week", "YYYY-MM-DD"), chronological=True),
    "month": Dimension("Ay", lambda _: _period("month", "YYYY-MM"), chronological=True),
}

MEASURES: dict[str, Measure] = {
    "count": Measure("Haber sayısı", lambda: func.count()),
    "sources": Measure("Farklı kaynak", lambda: func.count(distinct(Article.source_id))),
    "avg_importance": Measure(
        "Ortalama önem",
        lambda: func.avg(ArticleEnrichment.importance_score),
        decimals=3,
        needs=("enrichment",),
    ),
    "avg_confidence": Measure(
        "Ortalama güven",
        lambda: func.avg(ArticleEnrichment.confidence_score),
        decimals=3,
        needs=("enrichment",),
    ),
    "corroboration": Measure(
        "Doğrulayan kaynak toplamı",
        lambda: func.sum(ArticleEnrichment.corroborating_source_count),
        needs=("enrichment",),
    ),
}

# Filter keys the endpoint accepts, and where each one is evaluated.
ENRICHMENT_FILTERS: dict[str, Any] = {
    "category": ArticleEnrichment.category,
    "subcategory": ArticleEnrichment.subcategory,
    "region": ArticleEnrichment.region,
    "sentiment": ArticleEnrichment.sentiment,
}
FILTER_KEYS: tuple[str, ...] = (*ENRICHMENT_FILTERS, "airline", "source", "days")


def _apply_filters(query, filters: dict):
    """The pivot's WHERE clause. Mirrors ArticleRepository._apply_filters --
    notably the airline *semi-join*: `Article.id IN (subquery)` rather than a
    JOIN, so filtering by carrier can never duplicate an article and inflate a
    cell."""
    # Duplicates are collapsed into their canonical article by the dedup pass;
    # counting them would make every aggregate on this page wrong.
    query = query.where(Article.is_duplicate.is_(False))

    days = filters.get("days")
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=int(days))
        query = query.where(_DAY_EXPR >= since)

    for key, column in ENRICHMENT_FILTERS.items():
        value = filters.get(key)
        if value:
            query = query.where(column == value)

    source = filters.get("source")
    if source:
        # aliased(): `source` may already be in the FROM as a pivot dimension,
        # and an un-aliased subquery would auto-correlate to it and always
        # match.
        src = aliased(Source)
        query = query.where(Article.source_id.in_(select(src.id).where(src.name == source)))

    airline = filters.get("airline")
    if airline:
        mentions = (
            select(ArticleEntity.article_id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(Entity.entity_type == "airline")
        )
        if airline == "RIVALS":
            mentions = mentions.where(Entity.code.in_(RIVAL_CODES))
        elif airline != "ALL":
            mentions = mentions.where(Entity.code == airline)
        query = query.where(Article.id.in_(mentions))
    return query


def _label(value: Any) -> str:
    return NULL_LABEL if value is None else str(value)


def _quantize(value: Any, decimals: int | None) -> float | int | None:
    if value is None:
        return None
    return round(float(value), decimals) if decimals else int(value)


def _order(keys: dict[str, Any], chronological: bool) -> list[str]:
    if chronological:
        return sorted(keys)  # ISO text sorts chronologically
    return sorted(keys, key=lambda key: (-(float(keys[key] or 0)), key))


async def build_pivot(
    db: AsyncSession,
    rows: str,
    cols: str | None = None,
    measure: str = "count",
    filters: dict | None = None,
) -> dict:
    """One GROUP BY CUBE query behind the pivot table.

    Returns cells keyed "row|col" plus the totals band, all computed by
    Postgres over the real rows (see the module docstring on why the totals are
    not summed in Python).
    """
    filters = filters or {}
    if rows not in DIMENSIONS:
        raise ValueError(f"Geçersiz satır boyutu: {rows}")
    if cols is not None and cols not in DIMENSIONS:
        raise ValueError(f"Geçersiz sütun boyutu: {cols}")
    if measure not in MEASURES:
        raise ValueError(f"Geçersiz ölçü: {measure}")
    # Pivoting a dimension against itself is a diagonal, not a table.
    if cols == rows:
        cols = None

    row_dim = DIMENSIONS[rows]
    col_dim = DIMENSIONS[cols] if cols else None
    meas = MEASURES[measure]

    needs = set(row_dim.needs) | set(meas.needs)
    if col_dim:
        needs |= set(col_dim.needs)
    if any(filters.get(key) for key in ENRICHMENT_FILTERS):
        needs.add("enrichment")

    airline_sub = _airline_source() if "airline" in needs else None
    row_expr = row_dim.build(airline_sub)
    col_expr = col_dim.build(airline_sub) if col_dim else None

    selected = [row_expr.label("row_key"), func.grouping(row_expr).label("row_g")]
    if col_expr is not None:
        selected += [col_expr.label("col_key"), func.grouping(col_expr).label("col_g")]
    selected.append(meas.build().label("value"))

    query = select(*selected).select_from(Article)
    # All LEFT JOINs: the grand total must stay the same number of articles
    # whichever dimension the user drops onto the rows, so an article with no
    # enrichment (or no airline) still lands in a "(belirtilmemiş)" bucket
    # instead of vanishing from the table.
    if "enrichment" in needs:
        query = query.outerjoin(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
    if "source" in needs:
        query = query.outerjoin(Source, Source.id == Article.source_id)
    if airline_sub is not None:
        query = query.outerjoin(airline_sub, airline_sub.c.article_id == Article.id)

    query = _apply_filters(query, filters)
    query = query.group_by(
        func.cube(row_expr, col_expr) if col_expr is not None else func.rollup(row_expr)
    )

    records = (await db.execute(query)).all()

    cells: dict[str, Any] = {}
    row_totals: dict[str, Any] = {}
    col_totals: dict[str, Any] = {}
    grand_total: Any = None
    for record in records:
        mapping = record._mapping  # noqa: SLF001 -- documented Row API for labelled columns
        row_key = _label(mapping["row_key"])
        row_rolled = bool(mapping["row_g"])
        if col_expr is not None:
            col_key = _label(mapping["col_key"])
            col_rolled = bool(mapping["col_g"])
        else:
            col_key, col_rolled = "", True
        value = _quantize(mapping["value"], meas.decimals)

        if row_rolled and col_rolled:
            grand_total = value
        elif row_rolled:
            col_totals[col_key] = value
        elif col_rolled:
            row_totals[row_key] = value
        else:
            cells[f"{row_key}{CELL_SEPARATOR}{col_key}"] = value

    row_keys = _order(row_totals, row_dim.chronological)
    col_keys = _order(col_totals, col_dim.chronological) if col_dim else []
    truncated = len(row_keys) > MAX_ROWS or len(col_keys) > MAX_COLS
    row_keys = row_keys[:MAX_ROWS]
    col_keys = col_keys[:MAX_COLS]

    if truncated:
        kept_rows, kept_cols = set(row_keys), set(col_keys)
        row_totals = {key: row_totals[key] for key in row_keys}
        col_totals = {key: col_totals[key] for key in col_keys}
        cells = {
            key: value
            for key, value in cells.items()
            if (parts := key.rsplit(CELL_SEPARATOR, 1))
            and parts[0] in kept_rows
            and parts[1] in kept_cols
        }

    if grand_total is None and meas.decimals is None:
        grand_total = 0  # an empty count is zero; an empty average is nothing

    return {
        "rows": row_keys,
        "cols": col_keys,
        "cells": cells,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_total": grand_total,
        "measure": measure,
        "measure_label": meas.label,
        "decimals": meas.decimals or 0,
        "truncated": truncated,
        "dimensions": {
            "rows": rows,
            "rows_label": row_dim.label,
            "cols": cols,
            "cols_label": col_dim.label if col_dim else None,
        },
        "filters": {key: filters.get(key) for key in FILTER_KEYS if filters.get(key)},
    }


def describe() -> dict:
    """Whitelist as data, so the picker in the UI can never offer a dimension
    the backend would reject."""
    return {
        "dimensions": [
            {"slug": slug, "label": dim.label, "chronological": dim.chronological}
            for slug, dim in DIMENSIONS.items()
        ],
        "measures": [
            {"slug": slug, "label": meas.label, "decimals": meas.decimals or 0}
            for slug, meas in MEASURES.items()
        ],
        "filters": list(FILTER_KEYS),
        "default_days": DEFAULT_DAYS,
    }
