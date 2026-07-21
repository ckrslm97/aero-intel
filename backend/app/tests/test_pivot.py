"""The pivot builds its SQL from user-chosen dimensions, so these pin the two
things that could go wrong: the whitelist actually rejecting unknown slugs, and
the arithmetic (cells, the totals band, non-additive measures) matching the
rows that went in.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from app.api.v1.pivot import get_pivot
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.services.pivot_service import NULL_LABEL, build_pivot

NOW = datetime.now(timezone.utc)


async def _source(db, name: str) -> Source:
    source = Source(name=name, url=f"https://example.com/{name}", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(
    db,
    source,
    *,
    slug: str,
    category: str = "fleet",
    sentiment: str = "neutral",
    region: str | None = None,
    importance: float = 0.0,
    corroborating: int = 1,
    published_at: datetime | None = None,
    is_duplicate: bool = False,
    enriched: bool = True,
) -> Article:
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{slug}",
        title=slug,
        raw_content="body",
        published_at=published_at or NOW,
        fetched_at=published_at or NOW,
        content_hash=slug,
        status="enriched",
        is_duplicate=is_duplicate,
    )
    db.add(article)
    await db.flush()
    if enriched:
        db.add(
            ArticleEnrichment(
                article_id=article.id,
                category=category,
                sentiment=sentiment,
                region=region,
                importance_score=importance,
                confidence_score=0.5,
                corroborating_source_count=corroborating,
            )
        )
        await db.flush()
    return article


async def _airline(db, code: str, name: str) -> Entity:
    entity = Entity(entity_type="airline", name=name, code=code)
    db.add(entity)
    await db.flush()
    return entity


async def test_unknown_dimension_or_measure_is_a_400(db_session):
    for kwargs in (
        {"rows": "raw_content"},
        {"rows": "category", "cols": "; drop table articles"},
        {"rows": "category", "measure": "sum(price)"},
    ):
        with pytest.raises(HTTPException) as excinfo:
            await get_pivot(response=Response(), db=db_session, **kwargs)
        assert excinfo.value.status_code == 400
        assert "Geçersiz" in excinfo.value.detail


async def test_cells_and_totals_match_the_rows(db_session):
    source = await _source(db_session, "S")
    #                     category   sentiment
    await _article(db_session, source, slug="a1", category="fleet", sentiment="positive")
    await _article(db_session, source, slug="a2", category="fleet", sentiment="positive")
    await _article(db_session, source, slug="a3", category="fleet", sentiment="negative")
    await _article(db_session, source, slug="a4", category="network", sentiment="positive")
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", cols="sentiment", measure="count")

    assert pivot["rows"] == ["fleet", "network"]  # biggest row first
    assert sorted(pivot["cols"]) == ["negative", "positive"]
    assert pivot["cells"]["fleet|positive"] == 2
    assert pivot["cells"]["fleet|negative"] == 1
    assert pivot["cells"]["network|positive"] == 1
    assert "network|negative" not in pivot["cells"]  # empty combinations are absent
    assert pivot["row_totals"] == {"fleet": 3, "network": 1}
    assert pivot["col_totals"] == {"positive": 3, "negative": 1}
    assert pivot["grand_total"] == 4
    assert pivot["dimensions"] == {
        "rows": "category",
        "rows_label": "Kategori",
        "cols": "sentiment",
        "cols_label": "Duygu",
    }


async def test_null_dimension_values_get_their_own_bucket(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="r1", region="europe")
    await _article(db_session, source, slug="r2", region=None)
    # Never enriched at all -- still an article, so it must not vanish from the
    # grand total just because the user pivoted on an enrichment field.
    await _article(db_session, source, slug="r3", enriched=False)
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="region", measure="count")

    assert pivot["row_totals"] == {"europe": 1, NULL_LABEL: 2}
    assert pivot["grand_total"] == 3
    assert pivot["cols"] == []  # no column dimension -> the totals column only


async def test_distinct_source_totals_are_not_the_sum_of_the_cells(db_session):
    """`sources` is a COUNT(DISTINCT): one feed publishing into two categories
    contributes 1 to the grand total, not 2. This is why the totals come from
    GROUP BY CUBE instead of adding the cells up in Python."""
    source = await _source(db_session, "Shared Feed")
    await _article(db_session, source, slug="s1", category="fleet")
    await _article(db_session, source, slug="s2", category="network")
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", measure="sources")

    assert pivot["row_totals"] == {"fleet": 1, "network": 1}
    assert pivot["grand_total"] == 1


async def test_airline_filter_does_not_multiply_rows(db_session):
    """The carrier filter is a semi-join. An article mentioning Emirates twice
    over (plus another carrier) is still one article in the cell."""
    source = await _source(db_session, "S")
    emirates = await _airline(db_session, "EK", "Emirates")
    lufthansa = await _airline(db_session, "LH", "Lufthansa")

    both = await _article(db_session, source, slug="both", category="fleet")
    db_session.add(ArticleEntity(article_id=both.id, entity_id=emirates.id))
    db_session.add(ArticleEntity(article_id=both.id, entity_id=lufthansa.id))
    only_lh = await _article(db_session, source, slug="lh", category="fleet")
    db_session.add(ArticleEntity(article_id=only_lh.id, entity_id=lufthansa.id))
    await db_session.commit()

    filtered = await build_pivot(
        db_session, rows="category", measure="count", filters={"airline": "EK"}
    )
    assert filtered["row_totals"] == {"fleet": 1}
    assert filtered["grand_total"] == 1

    unfiltered = await build_pivot(db_session, rows="category", measure="count")
    assert unfiltered["grand_total"] == 2


async def test_airline_dimension_counts_each_mentioned_carrier(db_session):
    source = await _source(db_session, "S")
    emirates = await _airline(db_session, "EK", "Emirates")
    article = await _article(db_session, source, slug="ek", category="fleet")
    db_session.add(ArticleEntity(article_id=article.id, entity_id=emirates.id))
    # A country entity on the same article must not create a phantom row.
    country = Entity(entity_type="country", name="Turkey", code="TR")
    db_session.add(country)
    await db_session.flush()
    db_session.add(ArticleEntity(article_id=article.id, entity_id=country.id))
    await _article(db_session, source, slug="nobody", category="fleet")
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="airline", measure="count")

    assert pivot["row_totals"] == {"EK": 1, NULL_LABEL: 1}


async def test_duplicates_are_never_counted(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="original", category="fleet")
    await _article(db_session, source, slug="copy", category="fleet", is_duplicate=True)
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", measure="count")

    assert pivot["row_totals"] == {"fleet": 1}
    assert pivot["grand_total"] == 1


async def test_day_window_and_chronological_ordering(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="new", published_at=NOW - timedelta(days=1))
    await _article(db_session, source, slug="mid", published_at=NOW - timedelta(days=3))
    await _article(db_session, source, slug="old", published_at=NOW - timedelta(days=60))
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="day", measure="count", filters={"days": 30})

    assert pivot["grand_total"] == 2
    assert pivot["rows"] == sorted(pivot["rows"])  # calendar order, not by size
    assert len(pivot["rows"]) == 2


async def test_averages_are_rounded_to_three_places(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="i1", category="fleet", importance=0.1)
    await _article(db_session, source, slug="i2", category="fleet", importance=0.2)
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", measure="avg_importance")

    assert pivot["row_totals"]["fleet"] == pytest.approx(0.15)
    assert pivot["decimals"] == 3


async def test_corroboration_sums_over_the_filtered_rows(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="c1", category="fleet", corroborating=3)
    await _article(db_session, source, slug="c2", category="network", corroborating=2)
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", measure="corroboration")

    assert pivot["row_totals"] == {"fleet": 3, "network": 2}
    assert pivot["grand_total"] == 5


async def test_empty_result_does_not_crash(db_session):
    pivot = await build_pivot(
        db_session, rows="source", cols="category", measure="count", filters={"days": 7}
    )

    assert pivot["rows"] == []
    assert pivot["cols"] == []
    assert pivot["cells"] == {}
    assert pivot["grand_total"] == 0
    assert pivot["truncated"] is False


async def test_same_dimension_on_both_axes_collapses_to_one(db_session):
    source = await _source(db_session, "S")
    await _article(db_session, source, slug="x", category="fleet")
    await db_session.commit()

    pivot = await build_pivot(db_session, rows="category", cols="category", measure="count")

    assert pivot["cols"] == []
    assert pivot["dimensions"]["cols"] is None
    assert pivot["row_totals"] == {"fleet": 1}


async def test_source_filter_matches_by_name(db_session):
    wanted = await _source(db_session, "Wanted Feed")
    other = await _source(db_session, "Other Feed")
    await _article(db_session, wanted, slug="w", category="fleet")
    await _article(db_session, other, slug="o", category="fleet")
    await db_session.commit()

    pivot = await build_pivot(
        db_session, rows="source", measure="count", filters={"source": "Wanted Feed"}
    )

    assert pivot["row_totals"] == {"Wanted Feed": 1}
