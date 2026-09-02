"""Filter first, then translate -- and the flag that undoes it.

Translation is effectively the publication gate: the Gazete queries with
`translated_only=true`, so an untranslated article is one the reader never
sees. That makes these tests unusually load-bearing -- a wrong gate here does
not degrade the paper, it empties it.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.enrich import _should_translate, translate_pending_articles

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class _Settings:
    def __init__(self, floor=0.55, translate_all=False):
        self.translate_min_intelligence = floor
        self.translate_all_enriched = translate_all


# --- the gate predicate ------------------------------------------------------


def test_the_gate_opens_only_at_or_above_the_floor():
    settings = _Settings(floor=0.55)
    assert _should_translate(settings, 0.55) is True  # inclusive
    assert _should_translate(settings, 0.9) is True
    assert _should_translate(settings, 0.5499) is False
    assert _should_translate(settings, 0.0) is False


def test_the_escape_hatch_restores_the_old_behaviour_exactly():
    """The rollback. If the floor turns out to be wrong for the live feed's
    mix, the paper must be fixable with an environment variable rather than a
    release."""
    settings = _Settings(floor=0.99, translate_all=True)
    assert _should_translate(settings, 0.0) is True


def test_the_shipped_default_is_conservative():
    """A too-high floor empties the front page, which is worse than
    overspending -- so the default has to leave real headroom."""
    settings = get_settings()
    assert settings.translate_all_enriched is False
    assert 0.0 < settings.translate_min_intelligence <= 0.6


# --- the backlog queue -------------------------------------------------------


async def _pending(db, source, slug, intelligence):
    article = Article(
        source_id=source.id, url=f"https://example.com/tg/{slug}", title=slug,
        raw_content="body", published_at=NOW, fetched_at=NOW,
        content_hash=slug, status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id, headline=slug, summary="s",
            category="revenue_management", intelligence_score=intelligence,
        )
    )
    await db.flush()


class _Translator:
    name = "test-translator"

    async def translate(self, text, target="tr"):
        return f"tr:{text}"


async def test_the_backlog_queue_skips_articles_below_the_floor(db_session, monkeypatch):
    """Without this the gate buys nothing: the backlog would simply
    re-translate everything the inline gate declined, a run at a time."""
    monkeypatch.setattr("app.pipeline.enrich.get_llm_provider", lambda: _Translator())
    monkeypatch.setattr(
        "app.pipeline.enrich.get_settings", lambda: _Settings(floor=0.55)
    )

    source = Source(name="TG", url="https://example.com/tg", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _pending(db_session, source, "critical", 0.80)
    await _pending(db_session, source, "routine", 0.20)
    await db_session.commit()

    assert await translate_pending_articles(db_session, limit=10) == 1

    translated = [
        row.headline
        for row in (await db_session.execute(select(ArticleEnrichment))).scalars()
        if row.translated_at is not None
    ]
    assert translated == ["critical"]


async def test_an_unscored_row_is_not_translated_by_default(db_session, monkeypatch):
    """NULL means "never scored by this system", not "scored zero".

    Translating the pre-migration archive from the top is not what the budget
    is for; re-running enrich or select-critical is what lets an old row back
    into this queue.
    """
    monkeypatch.setattr("app.pipeline.enrich.get_llm_provider", lambda: _Translator())
    monkeypatch.setattr("app.pipeline.enrich.get_settings", lambda: _Settings(floor=0.55))

    source = Source(name="TG2", url="https://example.com/tg2", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _pending(db_session, source, "legacy", None)
    await db_session.commit()

    assert await translate_pending_articles(db_session, limit=10) == 0


async def test_the_flag_lets_the_whole_backlog_through_again(db_session, monkeypatch):
    """The same rollback, on the backlog path -- including the unscored rows."""
    monkeypatch.setattr("app.pipeline.enrich.get_llm_provider", lambda: _Translator())
    monkeypatch.setattr(
        "app.pipeline.enrich.get_settings", lambda: _Settings(floor=0.55, translate_all=True)
    )

    source = Source(name="TG3", url="https://example.com/tg3", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _pending(db_session, source, "routine", 0.20)
    await _pending(db_session, source, "legacy", None)
    await db_session.commit()

    assert await translate_pending_articles(db_session, limit=10) == 2


async def test_the_queue_is_ordered_by_intelligence_not_by_publisher(
    db_session, monkeypatch
):
    """`limit` is a budget, so ORDER BY decides who gets spent on."""
    monkeypatch.setattr("app.pipeline.enrich.get_llm_provider", lambda: _Translator())
    monkeypatch.setattr("app.pipeline.enrich.get_settings", lambda: _Settings(floor=0.55))

    source = Source(name="TG4", url="https://example.com/tg4", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    await _pending(db_session, source, "second", 0.60)
    await _pending(db_session, source, "first", 0.95)
    await _pending(db_session, source, "third", 0.56)
    await db_session.commit()

    assert await translate_pending_articles(db_session, limit=1) == 1
    translated = [
        row.headline
        for row in (await db_session.execute(select(ArticleEnrichment))).scalars()
        if row.translated_at is not None
    ]
    assert translated == ["first"]
