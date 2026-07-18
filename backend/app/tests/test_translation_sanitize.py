"""Guards against the production incident where llama-3.1-8b appended invented
article prose and translator meta-commentary after correct headline
translations (61 rows, worst case 7,513 chars). Patterns below are taken from
the actual corrupted rows.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.llm.sanitize import clean_translation
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.enrich import repair_corrupt_translations

HEADLINE_EN = "Report: Aer Lingus to Cut Some U.S. Routes"

# Verbatim shape of the production corruption: correct first line, then a blank
# line, then invented article prose.
CORRUPT_TR = (
    "Aer Lingus, Bazı ABD Rotalarını Kesecek\n\n"
    "İrlanda'nın ulusal havayolu Aer Lingus, ABD'deki bazı rotalarını azaltacak. "
    "Şirket, Dublin'den Denver, Minneapolis ve Las Vegas'a uçuşları durduracak. " * 5
)

META_TR = (
    "Zero Gravity ZG-T6 \n\n"
    "(Çevirisi yok, metni tam olarak çeviriyorum)\n\n"
    "Zero Gravity ZG-T6, 12 Temmuz'da Miami International'a indi."
)


def test_keeps_only_the_first_line_for_headlines():
    assert clean_translation(HEADLINE_EN, CORRUPT_TR) == "Aer Lingus, Bazı ABD Rotalarını Kesecek"


def test_strips_translator_meta_commentary():
    cleaned = clean_translation("Zero Gravity ZG-T6", META_TR)
    assert cleaned == "Zero Gravity ZG-T6"
    assert "çeviriyorum" not in cleaned


def test_strips_wrapping_quotes():
    assert clean_translation("Hello world", '"Merhaba dünya"') == "Merhaba dünya"


def test_none_and_empty_stay_none():
    assert clean_translation("Anything", None) is None
    assert clean_translation("Anything", "   \n  ") is None


def test_runaway_length_returns_none_not_junk():
    # A "translation" 50x the source length is invention, not translation --
    # and for a long source, first-line trimming doesn't apply, so the length
    # guard is the only defence.
    long_source = "word " * 60  # ~300 chars: treated as a summary
    junk = "kelime " * 500
    assert clean_translation(long_source, junk) is None


def test_summaries_keep_multiple_sentences():
    source = (
        "The airline reported record profits this quarter. Capacity grew ten "
        "percent while unit costs fell. Management raised full-year guidance "
        "on the back of strong transatlantic demand and premium cabins."
    )
    translated = (
        "Havayolu bu çeyrekte rekor kâr açıkladı. Kapasite yüzde on büyürken "
        "birim maliyetler düştü. Yönetim yıl sonu beklentisini yükseltti."
    )
    assert clean_translation(source, translated) == translated


async def test_repair_fixes_in_place_and_renulls_the_unsalvageable(db_session):
    source = Source(name="S", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    async def _row(url_suffix, headline, headline_tr):
        article = Article(
            source_id=source.id,
            url=f"https://example.com/{url_suffix}",
            title=headline,
            raw_content="body",
            fetched_at=datetime.now(timezone.utc),
            content_hash=f"hash-{url_suffix}",
            status="enriched",
        )
        db_session.add(article)
        await db_session.flush()
        enrichment = ArticleEnrichment(
            article_id=article.id,
            headline=headline,
            summary="A summary.",
            category="fleet",
            headline_tr=headline_tr,
            translated_at=datetime.now(timezone.utc),
            translation_provider="openai_compat",
        )
        db_session.add(enrichment)
        await db_session.flush()
        return enrichment.article_id

    salvageable_id = await _row("fixable", HEADLINE_EN, CORRUPT_TR)
    # First line empty -> nothing salvageable -> must be re-queued, not shown.
    hopeless_id = await _row("hopeless", "Some headline", "\n\n" + "uydurma metin " * 40)
    # A healthy row must not be touched.
    healthy_id = await _row("healthy", "Fine headline", "Sağlıklı başlık")

    result = await repair_corrupt_translations(db_session)
    assert result == {"repaired": 1, "renulled": 1}

    rows = {
        e.article_id: e
        for e in (await db_session.execute(select(ArticleEnrichment))).scalars()
    }
    assert rows[salvageable_id].headline_tr == "Aer Lingus, Bazı ABD Rotalarını Kesecek"
    assert rows[salvageable_id].translated_at is not None
    assert rows[hopeless_id].headline_tr is None
    assert rows[hopeless_id].translated_at is None  # back in the translate queue
    assert rows[healthy_id].headline_tr == "Sağlıklı başlık"

    # Idempotent: a second run finds nothing left to fix.
    assert await repair_corrupt_translations(db_session) == {"repaired": 0, "renulled": 0}
