"""The newsletter HTML is the single source of truth for both the email and the
PDF (see app/email/render.py), so these assertions guard the reader-facing
Turkish output for both at once.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.tr_dates import format_date_range, format_long_date
from app.email.render import SECTION_LABELS, render_newsletter_html
from app.models.article import Article, ArticleEnrichment
from app.models.edition import Edition, EditionArticle
from app.models.source import Source


async def _make_edition(
    db_session,
    *,
    section: str = "top_story",
    translated: bool = False,
    edition_date: date = date(2026, 7, 12),
) -> Edition:
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    # URL deliberately does not echo the section slug -- a later assertion
    # checks that the raw slug never leaks into the rendered HTML.
    article = Article(
        source_id=source.id,
        url="https://example.com/story",
        title="Delta launches Tokyo route",
        raw_content="body",
        fetched_at=datetime.now(timezone.utc),
        content_hash=f"hash-{section}",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Delta launches new Tokyo route",
            summary="Delta will begin nonstop service to Tokyo.",
            headline_tr="Delta yeni Tokyo hattını açıyor" if translated else None,
            summary_tr="Delta Tokyo hattına kesintisiz sefer başlatacak." if translated else None,
            translated_at=datetime.now(timezone.utc) if translated else None,
            translation_provider="openai_compat" if translated else None,
            category=section,
            importance_score=0.8,
            confidence_score=0.9,
            corroborating_source_count=2,
        )
    )
    await db_session.flush()

    edition = Edition(
        edition_date=edition_date,
        headline="Delta launches new Tokyo route",
        executive_summary="A quiet news day.",
        status="published",
    )
    db_session.add(edition)
    await db_session.flush()
    db_session.add(
        EditionArticle(edition_id=edition.id, article_id=article.id, section=section, rank=0)
    )
    await db_session.commit()

    result = await db_session.execute(
        select(Edition)
        .options(
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.source),
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.enrichment),
        )
        .where(Edition.id == edition.id)
    )
    return result.scalar_one()


# --- Pure formatting (no DB): the masthead date and event ranges ---

def test_format_long_date_matches_the_real_calendar():
    # 16 July 2026 is a Thursday; the weekday must be derived, not guessed.
    assert format_long_date(date(2026, 7, 16)) == "16 Temmuz 2026, Perşembe"
    assert format_long_date(date(2027, 1, 1)) == "1 Ocak 2027, Cuma"


def test_format_date_range_spans_a_month_boundary():
    assert format_date_range(date(2026, 7, 20), date(2026, 7, 24)) == "20-24 Temmuz 2026"
    assert format_date_range(date(2027, 5, 30), date(2027, 6, 1)) == "30 Mayıs - 1 Haziran 2027"


def test_every_section_key_has_a_turkish_label_none_left_in_english():
    # Mirrors the web labels in frontend/src/app/newspaper/[date]/page.tsx.
    expected = {
        "top_story", "general", "revenue_management", "safety", "finance",
        "fleet", "network", "regulatory", "sustainability", "labor",
        "airport", "events",
    }
    assert set(SECTION_LABELS) == expected
    english_leftovers = {"Top Stories", "Revenue Management", "Safety", "Network & Routes", "Events"}
    assert not (set(SECTION_LABELS.values()) & english_leftovers)
    # Every label carries a non-ASCII Turkish character OR is a known plain word.
    assert SECTION_LABELS["revenue_management"] == "Gelir Yönetimi"
    assert SECTION_LABELS["top_story"] == "Öne Çıkanlar"


# --- Rendered HTML ---

async def test_render_is_turkish_and_lists_the_article(db_session):
    edition = await _make_edition(db_session)
    html = render_newsletter_html(edition)

    assert 'lang="tr"' in html
    assert "Günün Manşeti" in html
    assert "%90 güven" in html
    assert "2 kaynak" in html
    assert "12 Temmuz 2026, Pazar" in html  # masthead date, TR
    # Every story is a link out to its source -- the email is a doorway.
    assert 'href="https://example.com/story"' in html
    # ...and the site itself is reachable from the footer links.
    assert "/newspaper/2026-07-12" in html
    # No English chrome left behind.
    assert "confidence" not in html
    assert "Top Stories" not in html


async def test_translated_article_shows_turkish_text_and_no_badge(db_session):
    edition = await _make_edition(db_session, translated=True)
    html = render_newsletter_html(edition)

    assert "Delta yeni Tokyo hattını açıyor" in html
    assert "Delta Tokyo hattına kesintisiz sefer başlatacak." in html
    # A genuinely-translated story must not be flagged as untranslated.
    assert "otomatik çeviri yok" not in html


async def test_untranslated_article_falls_back_to_english_with_a_badge(db_session):
    edition = await _make_edition(db_session, translated=False)
    html = render_newsletter_html(edition)

    # Falls back to the original text rather than showing nothing...
    assert "Delta launches new Tokyo route" in html
    # ...and says so honestly, exactly like the web card does.
    assert "otomatik çeviri yok" in html


async def test_section_label_is_translated_for_non_top_story_sections(db_session):
    edition = await _make_edition(db_session, section="revenue_management")
    html = render_newsletter_html(edition)

    assert "Gelir Yönetimi" in html
    assert "revenue_management" not in html  # raw slug must not leak into the UI
