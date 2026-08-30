""""Neden önemli?" is a second model call, so the gate is the feature.

Translation is already the whole daily token budget (see app/llm/factory.py and
the note on llm_enrich_batch_size). An assessment on every article would
roughly double a live run's spend to answer a question nobody asked of a
routine wire story. Three independent gates therefore have to hold, and each
of them is tested here rather than trusted:

  * the story clears WHY_IMPORTANT_MIN_IMPORTANCE once focus-weighted,
  * the article was on the live path at all (the free heuristic cannot write
    Turkish prose, and must not silently produce an empty assessment), and
  * the run has budget left (settings.llm_why_important_per_run).
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.llm.heuristic import HeuristicProvider
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.enrich import (
    WHY_IMPORTANT_MIN_IMPORTANCE,
    _focus_weighted,
    enrich_pending_articles,
)

NOW = datetime.now(timezone.utc)

# A revenue-management story: the heuristic categorises this one from its own
# keywords (see test_pipeline_budget.py, which relies on the same text).
RM_TITLE = "Emirates raises fares on Gulf routes as demand outpaces capacity"
RM_BODY = (
    "The airline said unit revenue, yield and load factor all rose this quarter, "
    "with a fare sale planned and dynamic pricing rolled out across the network."
)
# A fleet story: real aviation news, no focus bonus, so it stays under the bar.
FLEET_TITLE = "Boeing delivers the first 787 of the year to a European carrier"
FLEET_BODY = (
    "The aircraft was handed over at the manufacturer's delivery centre after "
    "maintenance checks; the carrier's fleet now numbers forty widebodies."
)


class AssessingProvider(HeuristicProvider):
    """A live provider, as far as the pipeline is concerned: it can translate
    and it can assess. Records every article it was asked about."""

    name = "test-assessor"

    def __init__(self):
        super().__init__()
        self.asked: list[str] = []

    async def translate(self, text, target="tr"):
        return f"tr:{text}"

    async def why_important(self, title, content, category):
        self.asked.append(title)
        return f"Bu haber {category} açısından önemlidir çünkü fiyat tarafını değiştiriyor."


async def _seed(db, provider, monkeypatch, articles):
    monkeypatch.setattr("app.pipeline.enrich.get_llm_provider", lambda: provider)
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_RELEVANCE_THRESHOLD", "0")  # every article is live-path

    source = Source(
        name=f"why-{id(articles)}",
        url=f"https://example.com/why-{id(articles)}",
        source_type="rss",
        trust_weight=0.8,
    )
    db.add(source)
    await db.flush()
    for slug, title, body in articles:
        db.add(
            Article(
                source_id=source.id,
                url=f"https://example.com/why/{slug}",
                title=title,
                raw_content=body,
                published_at=NOW,
                fetched_at=NOW,
                content_hash=slug,
                status="deduped",
            )
        )
    await db.commit()


async def _enrichment(db, title) -> ArticleEnrichment:
    result = await db.execute(
        select(ArticleEnrichment)
        .join(Article, Article.id == ArticleEnrichment.article_id)
        .where(Article.title == title)
    )
    return result.scalar_one()


def test_the_gate_is_the_focus_weighted_score_not_the_raw_one():
    """Raw importance measures how widely SYNDICATED a story is, so a flat
    floor on it would buy assessments for the Boeing order ten wires carried
    and none for the single-sourced fare move the desk needs explained. Same
    weighting the Gazete filters on and the front page ranks by."""
    importance = 0.49  # a typical stored value; the corpus sits in 0.455-0.490
    assert _focus_weighted(importance, "revenue_management") >= WHY_IMPORTANT_MIN_IMPORTANCE
    assert _focus_weighted(importance, "fleet") < WHY_IMPORTANT_MIN_IMPORTANCE


async def test_a_priority_story_gets_an_assessment(db_session, monkeypatch):
    provider = AssessingProvider()
    await _seed(db_session, provider, monkeypatch, [("rm", RM_TITLE, RM_BODY)])

    await enrich_pending_articles(db_session, limit=5)

    enrichment = await _enrichment(db_session, RM_TITLE)
    assert enrichment.category == "revenue_management"
    assert enrichment.why_important_tr
    assert provider.asked == [RM_TITLE]
    get_settings.cache_clear()


async def test_a_below_threshold_story_is_never_asked_about(db_session, monkeypatch):
    """The point of the gate: no second call, and an honest NULL rather than a
    generated sentence about a routine delivery."""
    provider = AssessingProvider()
    await _seed(db_session, provider, monkeypatch, [("fleet", FLEET_TITLE, FLEET_BODY)])

    await enrich_pending_articles(db_session, limit=5)

    enrichment = await _enrichment(db_session, FLEET_TITLE)
    assert enrichment.why_important_tr is None
    assert provider.asked == []
    get_settings.cache_clear()


async def test_the_heuristic_path_produces_no_assessment(db_session, monkeypatch):
    """No live provider configured -> no `why_important` method -> NULL. The
    column must never hold a heuristic's idea of prose."""
    await _seed(db_session, HeuristicProvider(), monkeypatch, [("rm2", RM_TITLE, RM_BODY)])

    await enrich_pending_articles(db_session, limit=5)

    enrichment = await _enrichment(db_session, RM_TITLE)
    assert enrichment.why_important_tr is None
    get_settings.cache_clear()


async def test_the_per_run_ceiling_bounds_the_extra_spend(db_session, monkeypatch):
    """The importance gate is a property of the day's news; the ceiling is a
    property of the budget. A day where every wire runs a fare story must not
    quietly cost a second model call on all of them."""
    provider = AssessingProvider()
    await _seed(
        db_session,
        provider,
        monkeypatch,
        [(f"rm-{i}", f"{RM_TITLE} {i}", RM_BODY) for i in range(4)],
    )
    monkeypatch.setenv("LLM_WHY_IMPORTANT_PER_RUN", "1")
    get_settings.cache_clear()

    await enrich_pending_articles(db_session, limit=10)

    assert len(provider.asked) == 1
    rows = list((await db_session.execute(select(ArticleEnrichment))).scalars())
    assert sum(1 for row in rows if row.why_important_tr) == 1
    # The other three are still fully enriched -- the ceiling drops the extra
    # sentence, never the article.
    assert len(rows) == 4
    assert all(row.category for row in rows)
    get_settings.cache_clear()


async def test_a_failing_assessment_never_costs_the_article(db_session, monkeypatch):
    class BrokenProvider(AssessingProvider):
        async def why_important(self, title, content, category):
            raise RuntimeError("provider exploded")

    await _seed(db_session, BrokenProvider(), monkeypatch, [("rm3", RM_TITLE, RM_BODY)])

    assert await enrich_pending_articles(db_session, limit=5) == 1

    enrichment = await _enrichment(db_session, RM_TITLE)
    assert enrichment.why_important_tr is None
    assert enrichment.headline_tr  # everything else still landed
    get_settings.cache_clear()
