"""Round-8 Phase 0: the levers that decide where the LLM budget goes.

Measured before this work: ingest brought in 250-700 articles/day against a
144-article LLM capacity, every article took the full LLM path regardless of
relevance, translation spent two 70b calls per article, and a failed summary
translation discarded a perfectly good headline translation.
"""
from datetime import datetime, timezone

from app.llm.openai_compat import _split_translation_pair
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.enrich import _translate_pair, enrich_pending_articles
from app.pipeline.relevance import score_article

NOW = datetime.now(timezone.utc)


# --- the relevance gate ---

def test_commercial_story_scores_far_above_an_unrelated_one():
    commercial = score_article(
        "Emirates raises fares as demand outpaces capacity on Gulf routes",
        "The airline said unit revenue and load factor both rose, with new route "
        "announcements and a fare sale planned for the winter season.",
    )
    unrelated = score_article(
        "Airport cat adopted by ground crew becomes local celebrity",
        "Staff at the terminal have named the stray and built it a small house.",
    )
    assert commercial.score > unrelated.score
    assert commercial.category == "revenue_management"


def test_focus_beats_outrank_equally_matched_side_categories():
    """A pricing story and a safety story with comparable keyword density must
    not be equal: the budget belongs to the beats this portal exists for."""
    pricing = score_article(
        "Airline pricing shake-up: new fare classes and dynamic pricing",
        "Fares, yield and unit revenue are all in play.",
    )
    safety = score_article(
        "Runway incursion investigation continues",
        "Investigators examined the incident and the emergency response.",
    )
    assert pricing.score > safety.score


async def test_low_relevance_articles_skip_the_llm_but_stay_searchable(db_session, monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_RELEVANCE_THRESHOLD", "6")

    source = Source(name="Gate", url="https://example.com/gate", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    db_session.add_all(
        [
            Article(
                source_id=source.id, url="https://example.com/rm",
                title="Lufthansa lifts fares as unit revenue and load factor climb",
                raw_content=(
                    "Pricing, yield and capacity discipline drove the quarter; the "
                    "carrier also announced a new route and a fare sale."
                ),
                published_at=NOW, fetched_at=NOW, content_hash="rm", status="deduped",
            ),
            Article(
                source_id=source.id, url="https://example.com/cat",
                title="Terminal cat adopted by ground staff",
                raw_content="The stray now has a small house near the gate.",
                published_at=NOW, fetched_at=NOW, content_hash="cat", status="deduped",
            ),
        ]
    )
    await db_session.commit()

    assert await enrich_pending_articles(db_session) == 2

    from sqlalchemy import select

    rows = {
        row.headline: row
        for row in (await db_session.execute(select(ArticleEnrichment))).scalars()
    }
    # Both were enriched -- the gate decides HOW, never whether.
    assert len(rows) == 2
    for enrichment in rows.values():
        assert enrichment.category  # filterable
        assert enrichment.summary is not None  # searchable

    get_settings.cache_clear()


# --- paired translation ---

def test_split_translation_pair_reads_both_fields():
    headline, summary = _split_translation_pair(
        "HEADLINE: Emirates ücretleri artırdı\nSUMMARY: Talep kapasiteyi aştı."
    )
    assert headline == "Emirates ücretleri artırdı"
    assert summary == "Talep kapasiteyi aştı."


def test_split_translation_pair_accepts_turkish_markers_and_wrapped_lines():
    headline, summary = _split_translation_pair(
        "BAŞLIK: Yeni hat açıldı\nÖZET: Havayolu kış tarifesinde\nyeni bir rota ekledi."
    )
    assert headline == "Yeni hat açıldı"
    assert summary == "Havayolu kış tarifesinde yeni bir rota ekledi."


def test_split_translation_pair_signals_failure_instead_of_guessing():
    """An unparsable answer must fall back to two calls, never truncate silently."""
    assert _split_translation_pair("Emirates ücretleri artırdı.") == (None, None)
    assert _split_translation_pair("") == (None, None)
    assert _split_translation_pair(None) == (None, None)


async def test_translate_pair_uses_one_call_when_the_provider_supports_it():
    class PairProvider:
        def __init__(self):
            self.single_calls = 0
            self.pair_calls = 0

        async def translate(self, text, target="tr"):
            self.single_calls += 1
            return f"tr:{text}"

        async def translate_pair(self, headline, summary, target="tr"):
            self.pair_calls += 1
            return f"tr:{headline}", f"tr:{summary}"

    provider = PairProvider()
    assert await _translate_pair(provider, "Fares rise", "Demand is strong") == (
        "tr:Fares rise",
        "tr:Demand is strong",
    )
    assert (provider.pair_calls, provider.single_calls) == (1, 0)


async def test_translate_pair_degrades_for_providers_without_the_method():
    class PlainProvider:
        def __init__(self):
            self.calls = 0

        async def translate(self, text, target="tr"):
            self.calls += 1
            return f"tr:{text}"

    provider = PlainProvider()
    assert await _translate_pair(provider, "Fares rise", "Demand is strong") == (
        "tr:Fares rise",
        "tr:Demand is strong",
    )
    assert provider.calls == 2


async def test_a_translated_headline_survives_a_failed_summary(db_session):
    """The card shows the headline. Throwing away a good headline translation
    because the summary call failed left articles needlessly English."""
    from unittest.mock import patch

    source = Source(name="Partial", url="https://example.com/p", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    db_session.add(
        Article(
            source_id=source.id, url="https://example.com/partial",
            title="Airline raises fares as unit revenue and yield climb",
            raw_content="Pricing and capacity discipline drove the quarter.",
            published_at=NOW, fetched_at=NOW, content_hash="partial", status="deduped",
        )
    )
    await db_session.commit()

    async def half_translated(engine, headline, summary):
        return "Havayolu ücretleri artırdı", None

    with patch("app.pipeline.enrich._translate_pair", half_translated):
        await enrich_pending_articles(db_session)

    from sqlalchemy import select

    enrichment = (await db_session.execute(select(ArticleEnrichment))).scalar_one()
    assert enrichment.headline_tr == "Havayolu ücretleri artırdı"
    assert enrichment.summary_tr is None
    assert enrichment.translated_at is not None  # honestly translated, partially


# --- gate calibration, pinned against what production actually looks like ---

def test_watched_carrier_headlines_always_clear_the_gate():
    """Calibration against 400 production articles caught the gate dropping
    "Turkish Airlines Targets Lima As Latin America Expansion Continues" -- a
    story about the home carrier -- purely for being briefly worded."""
    for title in (
        "Turkish Airlines Targets Lima As Latin America Expansion Continues",
        "Turkish Airlines to Fly Daily to Dushanbe",
        "Emirates launches massive promotion for transit passengers",
        "Qatar Airways offers discount to Athens",
    ):
        assert score_article(title, "").score >= 6, title


def test_campaign_headlines_survive_terse_wording():
    """Rival campaign coverage -- the thing this desk is asked to watch -- is
    written as one-liners, so keyword density alone scored it below an
    unrelated but wordy article."""
    campaign = score_article("Buy Avios points via Finnair Plus with a 40% discount", "")
    filler = score_article(
        "Airport cat adopted by ground crew becomes local celebrity",
        "Staff at the terminal have named the stray and built it a small house near "
        "the gate, and passengers now stop to take photographs of it every morning.",
    )
    assert campaign.score >= 6
    assert campaign.score > filler.score


def test_headline_only_items_are_not_punished_for_having_no_body():
    """804 of 997 waiting articles carry under 120 characters of body: the
    Google News radars deliver headlines only. Scoring them on the same scale
    as full articles gated them out for their length, not their subject."""
    headline = "Delta raises fares as unit revenue climbs"
    stub = score_article(headline, f"{headline} AJC.com")
    full = score_article(
        headline,
        "Delta said fares and unit revenue rose through the quarter as capacity "
        "discipline held and demand stayed strong across its network.",
    )
    assert stub.score >= 6
    assert full.score >= stub.score  # a real body still counts for more


def test_truly_unrelated_stories_are_still_gated_out():
    """The gate has to actually gate -- otherwise it buys nothing."""
    for title in (
        "Airport cat adopted by ground crew",
        "How Sherpa is transforming travel documentation",
    ):
        assert score_article(title, "").score < 6, title


async def test_the_single_call_path_survives_every_wrapper():
    """Regression: BudgetedProvider asked FallbackProvider for translate_pair,
    FallbackProvider didn't forward it, and the halving silently never reached
    production -- a live run still showed two 70b calls per article. Assert the
    capability travels through the whole stack."""
    from app.llm.factory import BudgetedProvider, FallbackProvider

    class CountingProvider:
        name = "counting"

        def __init__(self):
            self.pair_calls = 0
            self.single_calls = 0

        async def translate(self, text, target="tr"):
            self.single_calls += 1
            return f"tr:{text}"

        async def translate_pair(self, headline, summary, target="tr"):
            self.pair_calls += 1
            return f"tr:{headline}", f"tr:{summary}"

    inner = CountingProvider()
    stack = BudgetedProvider(FallbackProvider(inner))

    assert await _translate_pair(stack, "Fares rise", "Demand is strong") == (
        "tr:Fares rise",
        "tr:Demand is strong",
    )
    assert inner.pair_calls == 1
    assert inner.single_calls == 0  # the whole point: not two calls


async def test_an_already_enriched_article_is_never_picked_up_twice(db_session):
    """Regression: two workers on the same database -- a scheduled run and a
    manual dispatch -- both selected the same 'deduped' articles, and the
    second INSERT died on article_enrichment's unique constraint, taking the
    whole run down. It also heals rows whose status update was lost to an
    earlier crash: an enrichment row means the article is done."""
    source = Source(name="Race", url="https://example.com/race", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    article = Article(
        source_id=source.id, url="https://example.com/raced",
        title="Emirates raises fares as unit revenue climbs",
        raw_content="Pricing and yield moved this quarter.",
        published_at=NOW, fetched_at=NOW, content_hash="raced",
        status="deduped",  # stuck: enriched by another worker, status never updated
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id, headline="already done", category="revenue_management"
        )
    )
    await db_session.commit()

    # Must be a no-op, not a crash.
    assert await enrich_pending_articles(db_session) == 0
