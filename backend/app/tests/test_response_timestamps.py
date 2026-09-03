"""Every aggregate endpoint stamps its own answer, and states what it stamped.

Five endpoints -- /biz, /insights, /recommendations, /hubs and
/hubs/network-signals -- returned their numbers with no timestamp at all. On
the one of them that renders a "son güncelleme" (the Ağ Sinyalleri tab) that
meant printing the only time it had: the moment the BROWSER's fetch resolved --
a fact about the reader's network, which reads "now" on a cached response and
moves on every refresh. The other four printed nothing, and now have something
true to print. See app/api/window.py for which is which.

Three things are pinned per endpoint, and the last two are what make the first
mean anything:

1. the response carries `generated_at`, taken while the request was served;
2. the window it declares is the window it QUERIED -- `since` is exactly
   `generated_at - days`, and a row on the far side of that edge is genuinely
   absent from the payload;
3. a payload whose sections do NOT share one window declares them separately.
   /insights, /recommendations and /biz all reach outside a single range --
   four-times-wider review themes, a FORWARD event horizon -- and a lone
   `[since, until]` around that is a response misdescribing its own contents.

Without (2) the envelope would be decoration: a timestamp stapled on at
serialization time, describing a window adjacent to the one the SQL actually
cut.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Response

from app.api.v1 import biz, hubs, insights, recommendations
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.source import Source
from app.services.recommendations import EVENT_HORIZON_DAYS, TK_REVIEW_WINDOW_MULTIPLIER


async def _source(db) -> Source:
    source = Source(name="TS", url="https://example.com/ts", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, slug, *, published_at, entities=(), category="network"):
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{slug}",
        title=slug,
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(ArticleEnrichment(article_id=article.id, headline=slug, category=category))
    for entity in entities:
        db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


def _assert_stamped(payload: dict, *, before: datetime, after: datetime) -> datetime:
    """The stamp is a real instant from THIS request, timezone-aware."""
    generated = payload["generated_at"]
    assert isinstance(generated, datetime), "a stamp, not a pre-formatted string"
    assert generated.tzinfo is not None, "a naive UTC stamp renders as local time"
    assert before <= generated <= after
    return generated


def _assert_window(window: dict, generated: datetime, days: int) -> None:
    """The declared window is reproducible from the stamp -- so a client can
    render "son N gün" without inventing either end of it."""
    assert window["days"] == days
    assert window["until"] == generated
    assert window["since"] == generated - timedelta(days=days)


def _assert_horizon(window: dict, generated: datetime, days: int) -> None:
    """The forward twin. `until` is ahead of the stamp, which is the whole
    point: these items have not happened yet."""
    assert window["days"] == days
    assert window["since"] == generated
    assert window["until"] == generated + timedelta(days=days)


async def test_hubs_states_when_it_was_computed_and_over_what(db_session):
    before = datetime.now(timezone.utc)
    payload = await hubs.list_hubs(days=30, response=Response(), db=db_session)
    after = datetime.now(timezone.utc)

    generated = _assert_stamped(payload, before=before, after=after)
    _assert_window(payload["window"], generated, 30)
    # The list itself is untouched by the envelope.
    assert payload["hubs"] and "routes" in payload


async def test_the_hubs_window_is_the_window_that_was_queried(db_session):
    """The declared edge and the SQL edge are the same edge. A hub counted an
    article from outside the window it prints would make the stamp worse than
    useless -- it would put a precise time on a wrong number."""
    source = await _source(db_session)
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    db_session.add(ist)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await _article(
        db_session, source, "inside", published_at=now - timedelta(days=5), entities=[ist]
    )
    await _article(
        db_session, source, "outside", published_at=now - timedelta(days=40), entities=[ist]
    )
    await db_session.commit()

    payload = await hubs.list_hubs(days=30, response=Response(), db=db_session)
    ist_row = next(h for h in payload["hubs"] if h["code"] == "IST")

    assert ist_row["article_count"] == 1, "the older article is outside the window"
    since = payload["window"]["since"]
    assert now - timedelta(days=40) < since < now - timedelta(days=5), (
        "the printed edge sits between the row that counted and the row that did not"
    )


async def test_network_signals_returns_an_envelope_not_a_bare_list(db_session):
    before = datetime.now(timezone.utc)
    payload = await hubs.get_network_signals(days=30, response=Response(), db=db_session)
    after = datetime.now(timezone.utc)

    generated = _assert_stamped(payload, before=before, after=after)
    _assert_window(payload["window"], generated, 30)
    assert isinstance(payload["regions"], list)


async def test_biz_stamps_all_four_sections_with_one_instant(db_session):
    before = datetime.now(timezone.utc)
    payload = await biz.get_biz(days=30, response=Response(), db=db_session)
    after = datetime.now(timezone.utc)

    generated = _assert_stamped(payload, before=before, after=after)
    assert payload["days"] == 30
    assert set(payload) >= {
        "competitor_signals",
        "network_signals",
        "commercial_signals",
        "strategic_developments",
    }

    windows = payload["windows"]
    assert "window" not in payload, "no single window: this payload has six"
    # Three sections really are cut to `days`...
    for name in ("competitor_signals", "network_signals", "strategic_developments"):
        _assert_window(windows[name], generated, 30)
    # ...and the commercial block is not, which is the whole reason `windows`
    # is plural here. A single declared range would leave a third of
    # `commercial_signals` outside the window the payload claims for it.
    _assert_window(windows["commercial_comparison"], generated, 30)
    _assert_window(
        windows["commercial_tk_review_themes"], generated, 30 * TK_REVIEW_WINDOW_MULTIPLIER
    )
    _assert_horizon(windows["commercial_upcoming_events"], generated, EVENT_HORIZON_DAYS)
    # One instant, six windows: every edge is measured from the same stamp.
    assert {w["until"] for w in windows.values()} >= {generated}


async def test_the_biz_window_edge_is_the_edge_its_sections_queried(db_session):
    """The negative half, the one that makes the declaration mean something.

    `biz_overview` threads a single `now` into four sections, but every one of
    them takes `now` as OPTIONAL and falls back to its own clock. Deleting the
    anchor would leave the sections working and every assertion about the
    envelope's arithmetic still true -- so what is pinned here is the thing
    that would actually break: a row on the far side of the printed `since` is
    genuinely absent from the section, and a row just inside it is present.
    """
    source = await _source(db_session)
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(ek)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    inside = await _article(db_session, source, "ek-inside", published_at=now, entities=[ek])
    outside = await _article(
        db_session, source, "ek-outside", published_at=now, entities=[ek]
    )
    for slug, article, last_seen in (
        ("ek-inside", inside, now - timedelta(days=5)),
        ("ek-outside", outside, now - timedelta(days=40)),
    ):
        db_session.add(
            NewsEvent(
                slug=slug,
                title_tr=slug,
                primary_article_id=article.id,
                category="finance",
                first_seen=last_seen,
                last_seen=last_seen,
                is_published=True,
                confidence_band="high",
            )
        )
    await db_session.commit()

    payload = await biz.get_biz(days=30, response=Response(), db=db_session)
    since = payload["windows"]["competitor_signals"]["since"]

    rival = next(r for r in payload["competitor_signals"]["items"] if r["airline_code"] == "EK")
    assert rival["count"] == 1, "the 40-day-old event is outside the declared window"
    assert len(payload["strategic_developments"]["items"]) == 1, "same edge, same cut"
    assert now - timedelta(days=40) < since < now - timedelta(days=5), (
        "the printed edge sits between the event that counted and the one that did not"
    )


async def test_recommendations_stamps_the_window_it_compared(db_session):
    before = datetime.now(timezone.utc)
    # The multi-selects are passed explicitly: called as a plain function, an
    # unfilled `Query(None)` default is a FastAPI marker object, not None.
    payload = await recommendations.list_recommendations(
        days=7,
        category=None,
        region=None,
        airline=None,
        response=Response(),
        db=db_session,
    )
    after = datetime.now(timezone.utc)

    generated = _assert_stamped(payload, before=before, after=after)
    assert payload["count"] == len(payload["items"])

    # Not one window: the review themes look four times further back and the
    # calendar items look FORWARD, past `until` of everything else here.
    windows = payload["windows"]
    assert "window" not in payload
    assert set(windows) == {"comparison", "tk_review_themes", "upcoming_events"}
    _assert_window(windows["comparison"], generated, 7)
    _assert_window(windows["tk_review_themes"], generated, 7 * TK_REVIEW_WINDOW_MULTIPLIER)
    _assert_horizon(windows["upcoming_events"], generated, EVENT_HORIZON_DAYS)
    assert windows["upcoming_events"]["until"] > windows["comparison"]["until"], (
        "the event horizon is outside every backward window in this payload -- "
        "which is exactly what a single `window` would have hidden"
    )


async def test_insights_names_a_window_per_aggregate(db_session):
    """One `days` would misdescribe two thirds of this payload: momentum
    compares 7-day halves, the other two run over 30 days."""
    before = datetime.now(timezone.utc)
    payload = await insights.get_insights(response=Response(), db=db_session)
    after = datetime.now(timezone.utc)

    generated = _assert_stamped(payload, before=before, after=after)
    windows = payload["windows"]
    assert set(windows) == {
        "airline_momentum",
        "new_route_signals",
        "sentiment_by_category",
    }
    _assert_window(windows["airline_momentum"], generated, insights.MOMENTUM_WINDOW_DAYS)
    _assert_window(windows["new_route_signals"], generated, insights.ROUTE_WINDOW_DAYS)
    _assert_window(
        windows["sentiment_by_category"], generated, insights.SENTIMENT_WINDOW_DAYS
    )
    # Every aggregate is anchored to the SAME instant, not to three clocks read
    # one round trip apart.
    assert {w["until"] for w in windows.values()} == {generated}


async def test_the_insights_momentum_window_is_the_one_it_declares(db_session):
    """The negative half: an article older than the declared window does not
    contribute to the number printed under it."""
    source = await _source(db_session)
    airline = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(airline)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await _article(
        db_session,
        source,
        "recent-ek",
        published_at=now - timedelta(days=2),
        entities=[airline],
    )
    await _article(
        db_session,
        source,
        "ancient-ek",
        published_at=now - timedelta(days=90),
        entities=[airline],
    )
    await db_session.commit()

    payload = await insights.get_insights(response=Response(), db=db_session)
    mover = next(m for m in payload["airline_momentum"] if m["code"] == "EK")

    # 7 days current, the 7 before it as the comparison: the 90-day-old article
    # is in neither, so it moves nothing.
    assert mover["current"] == 1
    assert mover["previous"] == 0
