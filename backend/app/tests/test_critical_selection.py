"""The shortlist: the impact-call parser, the quota rule, and what gets written.

The quota rule is the load-bearing behaviour here and the one most likely to be
"improved" into a global top-N by someone who has not read why it is not one.
It gets a database-free test and an end-to-end one.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.llm.classify import parse_news_impact
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.services import news_scoring
from app.services.critical_selection import (
    DEFAULT_QUOTAS,
    apply_quotas,
    select_critical_articles,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


# --- the consolidated impact call: parsing ----------------------------------


def test_valid_json_parses_into_three_scores():
    outcome = parse_news_impact(
        '{"rm_impact": 0.9, "demand_impact": 0.4, "capacity_impact": 0.0,'
        ' "rationale_tr": "Rakip fiyat indirimi."}'
    )
    assert outcome.is_classified
    assert outcome.payload.rm_impact == 0.9
    assert outcome.payload.demand_impact == 0.4
    # 0.0 is a real answer and must survive as one, not be nulled out.
    assert outcome.payload.capacity_impact == 0.0
    assert outcome.payload.rationale_tr == "Rakip fiyat indirimi."


def test_a_fenced_or_chatty_response_still_parses():
    """Models wrap JSON in prose however firmly they are asked not to."""
    outcome = parse_news_impact(
        'Here you go:\n```json\n{"rm_impact": 0.5, "demand_impact": 0.5,'
        ' "capacity_impact": 0.5}\n```\nHope that helps!'
    )
    assert outcome.is_classified
    assert outcome.payload.rm_impact == 0.5


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json at all",
        "{broken",
        "[1, 2, 3]",  # a JSON array is not the object shape asked for
        '{"rm_impact": 0.5}',  # partial
        '{"rm_impact": 0.5, "demand_impact": 0.5}',  # still partial
        '{"rm_impact": "high", "demand_impact": 0.5, "capacity_impact": 0.5}',
        '{"rm_impact": null, "demand_impact": 0.5, "capacity_impact": 0.5}',
        '{"rm_impact": true, "demand_impact": 0.5, "capacity_impact": 0.5}',
    ],
)
def test_a_bad_or_partial_answer_fails_rather_than_half_scoring(raw):
    """A partial answer is rejected outright, not stored as two of three.

    news_scoring.combine renormalises over whichever components are present, so
    a payload carrying only rm_impact would silently produce a score weighted
    quite differently from its neighbours -- two articles ranked against each
    other on different rubrics.
    """
    outcome = parse_news_impact(raw)
    assert outcome.is_failure
    assert outcome.payload is None


def test_out_of_range_numbers_are_clamped_not_rejected():
    """A model answering 1.2 has said "as high as it goes", not garbage."""
    outcome = parse_news_impact(
        '{"rm_impact": 1.4, "demand_impact": -0.3, "capacity_impact": 0.5}'
    )
    assert outcome.is_classified
    assert outcome.payload.rm_impact == 1.0
    assert outcome.payload.demand_impact == 0.0


def test_a_missing_rationale_is_not_an_error():
    outcome = parse_news_impact(
        '{"rm_impact": 0.1, "demand_impact": 0.1, "capacity_impact": 0.1}'
    )
    assert outcome.is_classified
    assert outcome.payload.rationale_tr is None


def test_a_model_saying_the_word_null_is_read_as_null():
    outcome = parse_news_impact(
        '{"rm_impact": 0.1, "demand_impact": 0.1, "capacity_impact": 0.1,'
        ' "rationale_tr": "yok"}'
    )
    assert outcome.payload.rationale_tr is None


def test_an_essay_rationale_is_truncated_not_rejected():
    outcome = parse_news_impact(
        '{"rm_impact": 0.1, "demand_impact": 0.1, "capacity_impact": 0.1,'
        f' "rationale_tr": "{"uzun " * 200}"}}'
    )
    assert outcome.is_classified
    assert len(outcome.payload.rationale_tr) <= 400


# --- the quota rule, in isolation -------------------------------------------


def test_each_category_fills_its_own_quota():
    ranked = {
        "revenue_management": list(range(20)),
        "airport": list(range(20)),
        "events": list(range(20)),
    }
    selected = apply_quotas(ranked, {"revenue_management": 8, "airport": 5, "events": 5})
    assert len(selected["revenue_management"]) == 8
    assert len(selected["airport"]) == 5
    assert len(selected["events"]) == 5


def test_an_underfilled_category_does_not_hand_its_slots_to_another():
    """THE rule. Havalimanı genuinely produces ~3 stories a day; three real
    airport stories is an acceptable day, five padded ones is not.

    Written as its own test because a global top-N is the obvious
    "optimisation" and would pass every other test in this file.
    """
    ranked = {
        "revenue_management": list(range(50)),  # plenty
        "airport": [1, 2, 3],  # only three exist
        "events": [],  # none today
    }
    selected = apply_quotas(ranked, {"revenue_management": 8, "airport": 5, "events": 5})

    assert selected["airport"] == [1, 2, 3]
    assert selected["events"] == []
    # The 2 unused airport slots and 5 unused events slots do NOT become RM
    # slots: RM takes its own 8 and not one more.
    assert len(selected["revenue_management"]) == 8
    assert sum(len(v) for v in selected.values()) == 11  # 8 + 3 + 0, not 18


def test_a_category_with_no_quota_selects_nothing():
    assert apply_quotas({"fleet": [1, 2, 3]}, DEFAULT_QUOTAS)["fleet"] == []


def test_default_quotas_cover_exactly_the_three_printed_sections():
    assert set(DEFAULT_QUOTAS) == {"revenue_management", "airport", "events"}


# --- end to end --------------------------------------------------------------


async def _article(db, source, slug, category, published_at, title=None):
    article = Article(
        source_id=source.id,
        url=f"https://example.com/cs/{slug}",
        title=title or f"{slug} fare pricing yield capacity demand",
        raw_content="fare pricing yield revenue capacity demand load factor",
        published_at=published_at,
        fetched_at=NOW,
        content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id, headline=slug, summary="s", category=category
        )
    )
    await db.flush()
    return article


async def test_every_candidate_is_scored_but_only_the_shortlist_costs_a_call(
    db_session, monkeypatch
):
    """The two-pass shape: free score on everything, model on the quota."""
    calls = []

    async def fake_impact(title, content, category):
        calls.append(title)
        from app.llm.classify import NewsImpact
        from app.pipeline.outcomes import Outcome

        return Outcome.classified(
            NewsImpact(rm_impact=0.9, demand_impact=0.5, capacity_impact=0.2)
        )

    monkeypatch.setattr("app.llm.classify.score_news_impact", fake_impact)

    source = Source(name="CS", url="https://example.com/cs", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    for i in range(6):
        await _article(db_session, source, f"rm-{i}", "revenue_management", NOW)
    await db_session.commit()

    stats = await select_critical_articles(
        db_session, quotas={"revenue_management": 2}, now=NOW
    )

    assert stats["candidates"] == 6
    assert stats["scored"] == 6  # everything got the free score
    assert stats["shortlisted"] == 2  # only the quota reached the model
    assert stats["llm_scored"] == 2
    assert len(calls) == 2

    from sqlalchemy import select

    rows = list((await db_session.execute(select(ArticleEnrichment))).scalars())
    assert all(row.intelligence_score is not None for row in rows)
    assert all(row.score_detail for row in rows)
    # Four rows keep NULL impact columns: "nobody asked", not "no impact".
    scored_by_model = [r for r in rows if r.rm_impact is not None]
    assert len(scored_by_model) == 2
    assert len([r for r in rows if r.rm_impact is None]) == 4


async def test_the_quota_rule_holds_against_a_real_database(db_session, monkeypatch):
    """The no-spillover rule, end to end: RM is overflowing, airport has one
    story, and the run must not print five RM stories under airport's budget."""

    async def fake_impact(title, content, category):
        from app.llm.classify import NewsImpact
        from app.pipeline.outcomes import Outcome

        return Outcome.classified(
            NewsImpact(rm_impact=0.5, demand_impact=0.5, capacity_impact=0.5)
        )

    monkeypatch.setattr("app.llm.classify.score_news_impact", fake_impact)

    source = Source(name="CS2", url="https://example.com/cs2", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    for i in range(10):
        await _article(db_session, source, f"q-rm-{i}", "revenue_management", NOW)
    await _article(db_session, source, "q-ap-0", "airport", NOW)
    await db_session.commit()

    stats = await select_critical_articles(
        db_session, quotas={"revenue_management": 3, "airport": 4}, now=NOW
    )
    # 3 RM + the 1 airport story that exists = 4, NOT 3 + 4 = 7.
    assert stats["shortlisted"] == 4

    from sqlalchemy import select

    rows = list((await db_session.execute(select(ArticleEnrichment))).scalars())
    by_cat = {}
    for row in rows:
        if row.rm_impact is not None:
            by_cat[row.category] = by_cat.get(row.category, 0) + 1
    assert by_cat == {"revenue_management": 3, "airport": 1}


async def test_articles_outside_the_window_are_not_candidates(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.llm.classify.score_news_impact",
        lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    source = Source(name="CS3", url="https://example.com/cs3", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _article(db_session, source, "old", "revenue_management", NOW - timedelta(days=9))
    await db_session.commit()

    stats = await select_critical_articles(
        db_session, window_hours=48, use_llm=False, now=NOW
    )
    assert stats["candidates"] == 0


async def test_an_already_scored_article_is_not_re_asked(db_session, monkeypatch):
    """What bounds the daily spend: twelve runs a day must not cost 12 x quota.

    The same failure this PR fixes in app/pipeline/promotions.py.
    """
    calls = []

    async def fake_impact(title, content, category):
        calls.append(title)
        from app.llm.classify import NewsImpact
        from app.pipeline.outcomes import Outcome

        return Outcome.classified(
            NewsImpact(rm_impact=0.7, demand_impact=0.7, capacity_impact=0.7)
        )

    monkeypatch.setattr("app.llm.classify.score_news_impact", fake_impact)

    source = Source(name="CS4", url="https://example.com/cs4", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _article(db_session, source, "once", "revenue_management", NOW)
    await db_session.commit()

    first = await select_critical_articles(db_session, quotas={"revenue_management": 5}, now=NOW)
    second = await select_critical_articles(db_session, quotas={"revenue_management": 5}, now=NOW)

    assert first["llm_scored"] == 1
    assert second["candidates"] == 0
    assert second["llm_scored"] == 0
    assert len(calls) == 1


async def test_a_failed_model_call_leaves_a_usable_deterministic_score(
    db_session, monkeypatch
):
    """The article must still be rankable -- and its impact columns must stay
    NULL rather than being written as three zeroes."""

    async def failing(title, content, category):
        from app.pipeline.outcomes import Outcome

        return Outcome.failed("llm_call_error")

    monkeypatch.setattr("app.llm.classify.score_news_impact", failing)

    source = Source(name="CS5", url="https://example.com/cs5", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _article(db_session, source, "unlucky", "revenue_management", NOW)
    await db_session.commit()

    stats = await select_critical_articles(db_session, quotas={"revenue_management": 5}, now=NOW)
    assert stats["llm_failed"] == 1
    assert stats["llm_scored"] == 0

    from sqlalchemy import select

    row = (await db_session.execute(select(ArticleEnrichment))).scalars().one()
    assert row.intelligence_score is not None and row.intelligence_score > 0
    assert row.rm_impact is None
    assert row.score_detail["llm_scored"] is False


async def test_the_model_score_actually_changes_the_stored_score(db_session, monkeypatch):
    """Otherwise the whole second pass would be decorative."""

    async def fake_impact(title, content, category):
        from app.llm.classify import NewsImpact
        from app.pipeline.outcomes import Outcome

        return Outcome.classified(
            NewsImpact(
                rm_impact=1.0, demand_impact=1.0, capacity_impact=1.0,
                rationale_tr="Doğrudan fiyat etkisi.",
            )
        )

    monkeypatch.setattr("app.llm.classify.score_news_impact", fake_impact)

    source = Source(name="CS6", url="https://example.com/cs6", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _article(db_session, source, "boosted", "revenue_management", NOW)
    await db_session.commit()

    await select_critical_articles(db_session, quotas={"revenue_management": 1}, now=NOW)

    from sqlalchemy import select

    row = (await db_session.execute(select(ArticleEnrichment))).scalars().one()
    detail = row.score_detail
    assert detail["llm_scored"] is True
    assert set(detail["components"]) == set(news_scoring.WEIGHTS)
    assert detail["rationale_tr"] == "Doğrudan fiyat etkisi."

    # The stored score must be the one the model's answers produced, not the
    # deterministic-only score that pass 1 wrote a moment earlier. Compared
    # against the same components run back through combine() without the three
    # impact axes -- the exact number the row WOULD have kept had the call
    # failed.
    deterministic_only = news_scoring.combine(
        {
            name: value
            for name, value in detail["components"].items()
            if name not in news_scoring.LLM_COMPONENTS
        }
    ).intelligence_score
    assert row.intelligence_score == pytest.approx(detail["score"], abs=1e-4)
    assert row.intelligence_score != deterministic_only
