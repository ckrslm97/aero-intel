"""The wired pipeline, against a real database.

Every case here is deliberately named after the production failure it guards
against: the film review that became a high-severity attack, the campaign
attributed to whoever was mentioned most, the article that reached a Turkish
UI untranslated. classify_article is monkeypatched with recorded outcomes
rather than calling a real model -- CI must not depend on a model being
reachable or answering the same way twice.
"""
from datetime import datetime, timezone

import pytest

from app.agents import runner as runner_module
from app.agents.runner import run_pipeline_v2
from app.llm.classify import Classification, ClassificationResult, RiskAssessment
from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.source import Source
from app.pipeline.outcomes import Outcome


def _classified(**overrides) -> ClassificationResult:
    defaults = dict(
        category="revenue_management",
        subcategory="promotion",
        title_tr="Pegasus 6 hatta indirim kampanyası başlattı",
        summary_tr="Pegasus, altı hatta yüzde 50'ye varan indirim açıkladı.",
        confidence=None,
        airlines=[],
        airports=[],
        countries=[],
    )
    defaults.update(overrides)
    article_payload = Classification(
        category=defaults["category"],
        subcategory=defaults["subcategory"],
        title_tr=defaults["title_tr"],
        summary_tr=defaults["summary_tr"],
        confidence=defaults["confidence"],
        airlines=defaults["airlines"],
        airports=defaults["airports"],
        countries=defaults["countries"],
    )
    return ClassificationResult(
        article=Outcome.classified(article_payload, certainty=0.9),
        risk=Outcome.not_applicable("not_a_risk"),
        campaign=Outcome.not_applicable("not_a_campaign"),
    )


async def _source(db, name="Havayolu 101", trust=0.6) -> Source:
    source = Source(name=name, url=f"https://{name}.example/feed", source_type="rss", trust_weight=trust)
    db.add(source)
    await db.flush()
    return source


async def _entity(db, entity_type, name, code=None) -> Entity:
    entity = Entity(entity_type=entity_type, name=name, code=code)
    db.add(entity)
    await db.flush()
    return entity


async def _article(db, source, url, title, *, content="Havacılık haberi metni burada.", entities=()) -> Article:
    now = datetime.now(timezone.utc)
    article = Article(
        source_id=source.id,
        url=url,
        title=title,
        raw_content=content,
        fetched_at=now,
        published_at=now,
        content_hash=url[-32:],
        status="enriched",
    )
    db.add(article)
    await db.flush()
    for entity in entities:
        db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


@pytest.fixture(autouse=True)
def _stub_classifier(monkeypatch):
    """Default stand-in so tests that don't care about the classifier's
    answer don't need to supply one. Individual tests override via
    monkeypatch.setattr in their own body when the answer matters."""
    async def _default(title, content, *, topic_fragment=""):
        return _classified(title_tr=f"[TR] {title}")

    monkeypatch.setattr(runner_module, "classify_article", _default)
    yield


async def test_only_status_enriched_with_no_event_is_selected(db_session):
    """v2 must never compete with v1 for input -- it only ever picks up what
    v1 has already finished with."""
    source = await _source(db_session)
    await _article(db_session, source, "https://a.example/1", "Henüz işlenmemiş")
    pending = Article(
        source_id=source.id, url="https://a.example/2", title="Beklemede",
        fetched_at=datetime.now(timezone.utc), content_hash="pending", status="deduped",
    )
    db_session.add(pending)
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)
    assert stats["candidates"] == 1


async def test_a_published_event_is_created_from_a_single_article(db_session):
    source = await _source(db_session, trust=0.8)
    await _article(db_session, source, "https://a.example/x", "Pegasus'ta indirim kampanyası")

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["events"] == 1
    assert stats["published"] == 1
    events = (await db_session.execute(NewsEvent.__table__.select())).mappings().all()
    assert len(events) == 1
    assert events[0]["is_published"] is True
    assert events[0]["confidence_band"] in ("high", "medium")


async def test_foreign_language_articles_are_rejected_before_any_classify_call(db_session, monkeypatch):
    calls = []

    async def _tracking(title, content, *, topic_fragment=""):
        calls.append(title)
        return _classified()

    monkeypatch.setattr(runner_module, "classify_article", _tracking)

    source = await _source(db_session)
    await _article(
        db_session, source, "https://a.example/de",
        "Warum Premium-Reisende ihren Aperitif in den USA künftig früher abgeben müssen",
        content="Ein langer deutscher Artikeltext über Bordservice und Aperitifs an Bord.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["rejected_language"] == 1
    assert stats["events"] == 0
    assert calls == [], "a rejected-language article must never reach the classifier"

    article = (await db_session.execute(Article.__table__.select())).mappings().one()
    assert article["language"] == "de"
    assert article["rejection_reason"] == "language:de"
    assert article["event_id"] is None


async def test_off_domain_content_is_gated_out_before_classification(db_session, monkeypatch):
    """Credit-card content that cleared the old relevance gate on a bare
    'bonus' or 'offer' must not reach the classifier under the new one."""
    calls = []

    async def _tracking(title, content, *, topic_fragment=""):
        calls.append(title)
        return _classified()

    monkeypatch.setattr(runner_module, "classify_article", _tracking)

    source = await _source(db_session)
    await _article(
        db_session, source, "https://a.example/cc",
        "Get more than $4,000 in value with the 200,000-point bonus on the Chase Sapphire Reserve",
        content="A guide to credit card signup bonuses and how to maximize point value.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["rejected_gate"] == 1
    assert calls == []


async def test_the_veto_is_recorded_and_no_event_is_created(db_session, monkeypatch):
    """The film-review case: the model correctly says 'not a risk', and that
    answer must be recorded, not silently dropped or overridden."""
    async def _film_review(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.not_applicable("entertainment_coverage", certainty=0.95),
            risk=Outcome.not_applicable("entertainment_coverage"),
            campaign=Outcome.not_applicable("not_a_campaign"),
        )

    monkeypatch.setattr(runner_module, "classify_article", _film_review)

    source = await _source(db_session)
    await _article(
        db_session, source, "https://a.example/film",
        "Film Notları: The Bombing of Pan Am 103",
        content=(
            "Bu haftaki film önerimiz Pan Am 103 uçak kazasını konu alan bir belgesel. "
            "Havayolu tarihinde önemli yer tutan olay, yolcu ve kabin ekibi güvenliği "
            "açısından havacılık camiasında hâlâ konuşuluyor. Uçuş güvenliği uzmanları "
            "da belgeselde yorum yapıyor."
        ),
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["not_relevant"] == 1
    assert stats["events"] == 0

    article = (await db_session.execute(Article.__table__.select())).mappings().one()
    assert article["rejection_reason"] == "not_relevant:entertainment_coverage"
    assert article["event_id"] is None


async def test_a_risk_verdict_is_persisted_with_a_score(db_session, monkeypatch):
    async def _risk_answer(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="general", subcategory=None,
                    title_tr="Ukrayna Rus hava üssünü vurdu",
                    summary_tr="Ukrayna kuvvetleri bir Rus hava üssünü hedef aldı.",
                    confidence=0.9, airlines=[], airports=[], countries=["Russia"],
                ),
                certainty=0.9,
            ),
            risk=Outcome.classified(
                RiskAssessment(
                    type="war", severity="high", country="Russia", city=None,
                    aviation_impact="Hava üssü operasyonları etkilendi.",
                ),
                certainty=0.9,
            ),
            campaign=Outcome.not_applicable("not_a_campaign"),
        )

    monkeypatch.setattr(runner_module, "classify_article", _risk_answer)

    source = await _source(db_session, trust=0.85)
    await _article(
        db_session, source, "https://a.example/war", "Ukrayna Rus hava üssünde uçak vurdu",
        content=(
            "Ukrayna kuvvetleri bir Rus hava üssünde savaş uçak filosunu ve pilot eğitim "
            "tesisini hedef aldı, havacılık uzmanları saldırıyı değerlendirdi."
        ),
    )
    await db_session.commit()

    await run_pipeline_v2(db_session, limit=10)

    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    assert event["risk_type"] == "war"
    assert event["risk_family"] == "conflict"
    assert event["risk_severity"] == "high"
    assert event["risk_country"] == "Russia"
    assert event["risk_assessed_at"] is not None
    assert event["risk_score"] is not None
    assert event["region"] == "europe"


async def test_a_failed_classification_is_never_published(db_session, monkeypatch):
    async def _malformed(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.failed("json_parse_error"),
            risk=Outcome.failed("json_parse_error"),
            campaign=Outcome.failed("json_parse_error"),
        )

    monkeypatch.setattr(runner_module, "classify_article", _malformed)

    source = await _source(db_session)
    await _article(
        db_session, source, "https://a.example/fail", "Turkish Airlines announces new route",
        content="Turkish Airlines has announced a new route with additional flight frequency.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["failed"] == 1
    assert stats["events"] == 0
    article = (await db_session.execute(Article.__table__.select())).mappings().one()
    assert article["event_id"] is None
    assert article["rejection_reason"] == "classify_failed:json_parse_error"


async def test_a_low_confidence_event_is_stored_but_not_published(db_session, monkeypatch):
    """Missing required fields caps the band -- see pipeline/confidence.py.
    The event exists (audit trail); it must not be marked publishable."""
    async def _sparse(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="general", subcategory=None,
                    title_tr=None, summary_tr=None,
                    confidence=0.3, airlines=[], airports=[], countries=[],
                ),
                certainty=0.3,
            ),
            risk=Outcome.not_applicable("not_a_risk"),
            campaign=Outcome.not_applicable("not_a_campaign"),
        )

    monkeypatch.setattr(runner_module, "classify_article", _sparse)

    source = await _source(db_session, trust=0.5)
    await _article(
        db_session, source, "https://a.example/sparse", "Havayolu sektöründe belirsiz bir haber",
        content="Havacılık sektöründe belirsiz bir gelişme yaşandı, uçuş tarifesi ve bilet fiyatları etkilenebilir.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["events"] == 1
    assert stats["published"] == 0
    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    assert event["is_published"] is False
    assert event["confidence_band"] == "low"


async def test_clustered_articles_share_one_event_and_classification(db_session, monkeypatch):
    """Two tellings of the Turkish Airlines Lima launch: one event, one
    classification, on the primary -- not two rows, not two verdicts."""
    calls = []

    async def _tracking(title, content, *, topic_fragment=""):
        calls.append(title)
        return _classified(category="network", subcategory="new_route", title_tr="THY Lima hattını açıyor")

    monkeypatch.setattr(runner_module, "classify_article", _tracking)

    tk = await _entity(db_session, "airline", "Turkish Airlines", "TK")
    lim = await _entity(db_session, "airport", "Lima", "LIM")

    official = await _source(db_session, name="THY Basın", trust=0.95)
    agency = await _source(db_session, name="AeroTime", trust=0.7)

    await _article(
        db_session, official, "https://a.example/tk1",
        "Türk Hava Yolları Lima hattını açıyor", entities=[tk, lim],
    )
    await _article(
        db_session, agency, "https://a.example/tk2",
        "Turkish Airlines launches Lima route", entities=[tk, lim],
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["events"] == 1
    assert len(calls) == 1, "classification must run once per event, on the primary, not per article"

    articles = (await db_session.execute(Article.__table__.select())).mappings().all()
    event_ids = {a["event_id"] for a in articles}
    assert len(event_ids) == 1 and None not in event_ids

    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    assert event["article_count"] == 2
