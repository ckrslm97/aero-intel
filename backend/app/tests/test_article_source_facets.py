"""The Gazete's "Kaynak" chip row: which outlets filled the window, and the
`?source=` filter the chips send back.

The pair has to be checked together, because the whole reason the facet
endpoint exists is that a chip must never be able to ask for a name the filter
would miss. Counting the names on the loaded page instead would describe page 1
of a paginated list rather than the window -- which is what these tests pin
down alongside the plain filtering behaviour.
"""
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.repositories.article_repository import ArticleRepository

NOW = datetime.now(timezone.utc)


async def _source(db_session, name, *, tier=None, trust_weight=0.7):
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        source_type="rss",
        tier=tier,
        trust_weight=trust_weight,
    )
    db_session.add(source)
    await db_session.flush()
    return source


async def _article(db_session, source, *, category="fleet", published_at=NOW, translated=True):
    key = f"{source.name}-{category}-{published_at.isoformat()}-{translated}"
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{key}",
        title="t",
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=key,
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            category=category,
            translated_at=NOW if translated else None,
        )
    )
    await db_session.flush()
    return article


async def test_facets_name_the_busiest_outlets_first(db_session):
    reuters = await _source(db_session, "Reuters", tier="agency")
    trade = await _source(db_session, "Trade Weekly", tier="trade")
    # Distinct timestamps keep the URLs (and content hashes) unique.
    for minutes in (1, 2, 3):
        await _article(db_session, reuters, published_at=NOW - timedelta(minutes=minutes))
    await _article(db_session, trade, published_at=NOW - timedelta(hours=2))
    await db_session.commit()

    facets = await ArticleRepository(db_session).count_by_source()

    assert facets == [("Reuters", "agency", 3), ("Trade Weekly", "trade", 1)]


async def test_facets_report_the_effective_tier_of_an_undeclared_source(db_session):
    # No declared tier: the facet must resolve it through trust_weight exactly
    # as an article card's badge does, or a chip and a card would disagree
    # about the same outlet.
    regulator = await _source(db_session, "CAA", tier=None, trust_weight=0.95)
    await _article(db_session, regulator)
    await db_session.commit()

    facets = await ArticleRepository(db_session).count_by_source()

    assert facets == [("CAA", "regulator", 1)]


async def test_facets_honour_the_same_window_and_quality_filters_as_the_list(db_session):
    outlet = await _source(db_session, "Wire", tier="agency")
    await _article(db_session, outlet, published_at=NOW)
    await _article(db_session, outlet, published_at=NOW - timedelta(days=40))
    await _article(db_session, outlet, published_at=NOW - timedelta(hours=3), translated=False)
    await db_session.commit()

    repo = ArticleRepository(db_session)
    facets = await repo.count_by_source(
        since=NOW - timedelta(days=30), translated_only=True
    )

    # Only the in-window translated row survives -- a chip promising rows the
    # filtered list would never render is a chip that lies.
    assert facets == [("Wire", "agency", 1)]


async def test_facets_are_capped_by_limit(db_session):
    for index in range(3):
        outlet = await _source(db_session, f"Outlet {index}", tier="trade")
        for offset in range(index + 1):
            await _article(db_session, outlet, published_at=NOW - timedelta(minutes=offset))
    await db_session.commit()

    facets = await ArticleRepository(db_session).count_by_source(limit=2)

    assert [name for name, _, _ in facets] == ["Outlet 2", "Outlet 1"]


async def test_source_filter_keeps_only_the_named_outlets(db_session):
    reuters = await _source(db_session, "Reuters", tier="agency")
    trade = await _source(db_session, "Trade Weekly", tier="trade")
    await _article(db_session, reuters)
    await _article(db_session, trade)
    await db_session.commit()

    repo = ArticleRepository(db_session)
    rows = await repo.list_recent(source_names=["Reuters"])

    assert [row.source.name for row in rows] == ["Reuters"]
    # The count has to move with the list or "load more" pages past the end.
    assert await repo.count(source_names=["Reuters"]) == 1


async def test_source_filter_unions_repeated_values(db_session):
    reuters = await _source(db_session, "Reuters", tier="agency")
    trade = await _source(db_session, "Trade Weekly", tier="trade")
    other = await _source(db_session, "Blog", tier="aggregator")
    await _article(db_session, reuters)
    await _article(db_session, trade)
    await _article(db_session, other)
    await db_session.commit()

    repo = ArticleRepository(db_session)
    rows = await repo.list_recent(source_names=["Reuters", "Trade Weekly"])

    assert {row.source.name for row in rows} == {"Reuters", "Trade Weekly"}


async def test_no_source_filter_means_every_outlet(db_session):
    # The absent-parameter case is the default on every caller; an empty list
    # must behave the same way rather than silently matching nothing.
    reuters = await _source(db_session, "Reuters", tier="agency")
    trade = await _source(db_session, "Trade Weekly", tier="trade")
    await _article(db_session, reuters)
    await _article(db_session, trade)
    await db_session.commit()

    repo = ArticleRepository(db_session)
    assert await repo.count(source_names=None) == 2
    assert await repo.count(source_names=[]) == 2
