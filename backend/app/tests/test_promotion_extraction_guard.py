"""The promotion extractor stops re-reading the archive.

`_candidate_articles` had no memory: it returned every matching article in the
archive on every run, and the scheduled job runs at :10 and :40 -- 48 times a
day, one LLM call per candidate per run, growing with the archive forever. The
module's own comment already conceded the behaviour ("re-reads the same article
text every 30 minutes with an LLM whose answer is not stable to the field") and
used it to justify discarding the resulting version rows as audit noise.

These tests pin the fix: a run costs one call per NEW campaign article, not one
per archived one.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.promotion import Promotion
from app.models.source import Source
from app.pipeline.promotions import DEFAULT_EXTRACT_LIMIT, extract_promotions

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

_PAYLOAD = (
    '{"discount_pct": 40, "sale_starts": "2026-09-01", "sale_ends": "2026-09-30",'
    ' "travel_starts": null, "travel_ends": null, "markets": "Avrupa"}'
)


async def _campaign_article(db, source, slug, *, airline_entity, subcategory="promotion"):
    article = Article(
        source_id=source.id,
        url=f"https://example.com/pg/{slug}",
        title=f"{slug} kampanya %40 indirim",
        raw_content="Kampanya kapsaminda %40 indirim.",
        published_at=NOW,
        fetched_at=NOW,
        content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id,
            headline=slug,
            summary="s",
            category="revenue_management",
            subcategory=subcategory,
        )
    )
    db.add(ArticleEntity(article_id=article.id, entity_id=airline_entity.id))
    await db.flush()
    return article


async def _fixture(db, name="PG"):
    source = Source(name=name, url=f"https://example.com/{name}", source_type="rss")
    airline = Entity(entity_type="airline", name="Pegasus Airlines", code="PC")
    db.add_all([source, airline])
    await db.flush()
    return source, airline


def _counting_generator(calls):
    async def generate(prompt):
        calls.append(prompt)
        return _PAYLOAD

    return generate


async def test_a_second_run_does_not_re_ask_the_model(db_session, monkeypatch):
    """The leak, closed. This is the whole point of the change.

    Before: 48 runs/day x every archived campaign article = one LLM call each,
    forever. After: the article is read once.
    """
    calls = []
    monkeypatch.setattr(
        "app.llm.factory.get_raw_generator", lambda: _counting_generator(calls)
    )

    source, airline = await _fixture(db_session)
    await _campaign_article(db_session, source, "flash-sale", airline_entity=airline)
    await db_session.commit()

    first = await extract_promotions(db_session)
    assert first["scanned"] == 1
    assert len(calls) == 1

    second = await extract_promotions(db_session)
    assert second["scanned"] == 0
    # THE assertion: the second sweep spends nothing.
    assert len(calls) == 1


async def test_the_article_is_stamped_even_when_no_campaign_is_found(
    db_session, monkeypatch
):
    """A "not a campaign" answer is an answer, and must not be re-asked.

    This is the case a `NOT EXISTS (promotions WHERE url = ...)` guard would
    have missed entirely -- such an article never gets a promotions row under
    its own URL, so it would have been re-read forever.
    """
    calls = []

    async def barren(prompt):
        calls.append(prompt)
        return '{"discount_pct": null, "sale_starts": null, "sale_ends": null,' \
               ' "travel_starts": null, "travel_ends": null, "markets": null}'

    monkeypatch.setattr("app.llm.factory.get_raw_generator", lambda: barren)

    source, airline = await _fixture(db_session, name="PG2")
    await _campaign_article(db_session, source, "no-campaign", airline_entity=airline)
    await db_session.commit()

    await extract_promotions(db_session)
    assert len(calls) == 1

    row = (await db_session.execute(select(ArticleEnrichment))).scalars().one()
    assert row.promo_extracted_at is not None

    await extract_promotions(db_session)
    assert len(calls) == 1


async def test_a_failing_model_call_still_stamps_the_article(db_session, monkeypatch):
    """The heuristic fallback path must stamp too, or a provider outage turns
    into a permanent re-read loop over every article it touched."""
    calls = []

    async def exploding(prompt):
        calls.append(prompt)
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.llm.factory.get_raw_generator", lambda: exploding)

    source, airline = await _fixture(db_session, name="PG3")
    await _campaign_article(db_session, source, "outage", airline_entity=airline)
    await db_session.commit()

    stats = await extract_promotions(db_session)
    assert stats["scanned"] == 1
    assert len(calls) == 1
    # The regex reader answered instead, and the row is still marked read.
    row = (await db_session.execute(select(ArticleEnrichment))).scalars().one()
    assert row.promo_extracted_at is not None
    assert (await extract_promotions(db_session))["scanned"] == 0
    assert len(calls) == 1


async def test_a_new_article_is_still_picked_up_after_the_guard(db_session, monkeypatch):
    """The guard must bound cost without blinding the job."""
    calls = []
    monkeypatch.setattr(
        "app.llm.factory.get_raw_generator", lambda: _counting_generator(calls)
    )

    source, airline = await _fixture(db_session, name="PG4")
    await _campaign_article(db_session, source, "first", airline_entity=airline)
    await db_session.commit()
    await extract_promotions(db_session)
    assert len(calls) == 1

    await _campaign_article(db_session, source, "second", airline_entity=airline)
    await db_session.commit()
    stats = await extract_promotions(db_session)
    assert stats["scanned"] == 1
    assert len(calls) == 2
    assert len((await db_session.execute(select(Promotion))).scalars().all()) == 2


async def test_rescan_deliberately_replays_the_archive(db_session, monkeypatch):
    """A prompt change or model upgrade must still be replayable on purpose."""
    calls = []
    monkeypatch.setattr(
        "app.llm.factory.get_raw_generator", lambda: _counting_generator(calls)
    )

    source, airline = await _fixture(db_session, name="PG5")
    await _campaign_article(db_session, source, "replayed", airline_entity=airline)
    await db_session.commit()

    await extract_promotions(db_session)
    assert len(calls) == 1
    await extract_promotions(db_session, rescan=True)
    assert len(calls) == 2


async def test_the_default_limit_is_bounded(db_session, monkeypatch):
    """Unbounded used to be the default, which is how this became the most
    expensive job in the repo. `limit=None` is now something a caller has to
    ask for explicitly."""
    assert DEFAULT_EXTRACT_LIMIT > 0

    calls = []
    monkeypatch.setattr(
        "app.llm.factory.get_raw_generator", lambda: _counting_generator(calls)
    )
    source, airline = await _fixture(db_session, name="PG6")
    for i in range(5):
        await _campaign_article(db_session, source, f"many-{i}", airline_entity=airline)
    await db_session.commit()

    stats = await extract_promotions(db_session, limit=2)
    assert stats["scanned"] == 2
    assert len(calls) == 2
