"""The wired pipeline, against a real database.

Every case here is deliberately named after the production failure it guards
against: the film review that became a high-severity attack, the campaign
attributed to whoever was mentioned most, the article that reached a Turkish
UI untranslated. classify_article is monkeypatched with recorded outcomes
rather than calling a real model -- CI must not depend on a model being
reachable or answering the same way twice.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agents import runner as runner_module
from app.agents.campaign_airline import STALE_AFTER_DAYS
from app.agents.runner import run_pipeline_v2
from app.llm.classify import CampaignExtraction, Classification, ClassificationResult, RiskAssessment
from app.models.article import Article
from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
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
                    category="conflict", severity="high", probability=0.95,
                    aviation_impact_score=0.8, country="Russia", city=None,
                    aviation_impact_note="Hava üssü operasyonları etkilendi.",
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
    assert event["risk_type"] == "conflict"
    assert event["risk_family"] == "geopolitical"
    assert event["risk_severity"] == "high"
    # Lowercase, matching the existing convention: v1's detect_risk_place
    # also stores country.lower() so it lines up with COUNTRY_TO_REGION's keys.
    assert event["risk_country"] == "russia"
    assert event["risk_assessed_at"] is not None
    assert event["risk_score"] is not None
    assert event["region"] == "europe"
    # The score is a product of five factors, so the number alone cannot be
    # argued with -- a 0.08 does not say whether the event was minor, unlikely,
    # stale or thinly sourced. Both of these were computed and thrown away
    # before the row was written; they are the explanation half of the verdict.
    assert set(event["risk_score_detail"]) == {
        "severity", "probability", "aviation_impact", "recency", "source_tier",
    }
    assert event["risk_score_detail"]["probability"] == pytest.approx(0.95)
    assert event["aviation_impact_note"] == "Hava üssü operasyonları etkilendi."


async def test_an_anniversary_piece_is_vetoed_as_retrospective(db_session, monkeypatch):
    """The model, correctly, sees a devastating earthquake and says "risk".
    It is right about the hazard and wrong about the day: nothing in this
    pipeline carries an event date, only a publication time, so a commemoration
    filed this morning becomes a signal from this morning.

    A second validation layer over the model's verdict, the same shape as the
    campaign one -- it can only narrow, and it records WHY rather than quietly
    dropping the field.
    """
    async def _anniversary(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="general", subcategory=None,
                    title_tr="Kahramanmaraş depreminin yıl dönümü",
                    summary_tr="Depremde hayatını kaybedenler anıldı.",
                    confidence=0.9, airlines=[], airports=[], countries=["Turkey"],
                ),
                certainty=0.9,
            ),
            risk=Outcome.classified(
                RiskAssessment(
                    category="natural_disaster", severity="high", probability=0.9,
                    aviation_impact_score=0.5, country="Turkey", city=None,
                    aviation_impact_note="Havalimanları o dönem kapanmıştı.",
                ),
                certainty=0.9,
            ),
            campaign=Outcome.not_applicable("not_a_campaign"),
        )

    monkeypatch.setattr(runner_module, "classify_article", _anniversary)

    source = await _source(db_session)
    await _article(
        db_session, source, "https://a.example/anma",
        "Havalimanlarında deprem yıl dönümü anma törenleri: Türk Hava Yolları "
        "uçuş programını değiştirdi",
        content=(
            "6 Şubat depremlerinde hayatını kaybedenler havalimanlarında düzenlenen "
            "törenlerle anıldı. Türk Hava Yolları ve AJet, anma günü nedeniyle Hatay "
            "Havalimanı ve Adana Havalimanı seferlerinde tarife değişikliğine gitti. "
            "Depremde bölgedeki havalimanları günlerce yalnızca yardım uçuşlarına açık "
            "kalmış, pistteki hasar nedeniyle uçak trafiği durmuştu."
        ),
    )
    await db_session.commit()

    await run_pipeline_v2(db_session, limit=10)

    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    # The event is still published -- it is a real, relevant aviation story.
    # Only its risk verdict is withdrawn, and the reason is on the record.
    assert event["risk_type"] is None
    assert event["risk_severity"] is None
    assert event["risk_score"] is None
    assert event["not_applicable_reasons"]["risk"] == "retrospective"


async def test_a_non_risk_event_carries_no_score_breakdown_and_no_impact_note(db_session):
    """The default stub answers NOT_APPLICABLE for risk. Both new columns must
    stay null rather than land as an empty dict and an empty string -- "no
    risk assessment" and "an assessment that said nothing" are different
    facts, and only the first one is true here."""
    source = await _source(db_session)
    await _article(db_session, source, "https://a.example/plain", "Pegasus yeni hat açıyor")
    await db_session.commit()

    await run_pipeline_v2(db_session, limit=10)

    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    assert event["risk_score"] is None
    assert event["risk_score_detail"] is None
    assert event["aviation_impact_note"] is None


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


async def test_a_validated_campaign_produces_a_promotion_row(db_session, monkeypatch):
    """Balkanlar %50'ye Varan İndirimle! -- one of only two rows in production
    that were genuine, correctly-attributed, dated campaigns.

    THE SALE WINDOW IS RELATIVE TO TODAY, and it has to be. This test used to
    state 25--27 August 2026 outright, and it passed for exactly as long as the
    wall clock stayed within `campaign_airline.STALE_AFTER_DAYS` of that
    window: it went red on 4 September 2026 with `campaigns == 0`, on a commit
    whose only changes were in the frontend. The product was right -- a sale
    that closed eight days ago must not be published -- and the test was
    asserting the calendar rather than the behaviour it names.

    `run_pipeline_v2` takes no clock (the guard reads `date.today()`), so the
    fixture is what has to move. `test_campaign_airline.py` pins its own TODAY
    and passes it in; that is the same discipline, applied where it can be.
    """
    # An open sale: two days in, closing tomorrow.
    sale_starts = date.today() - timedelta(days=2)
    sale_ends = date.today() + timedelta(days=1)

    async def _campaign_answer(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="revenue_management", subcategory="promotion",
                    title_tr="Balkanlar %50'ye Varan İndirimle!",
                    summary_tr="Pegasus, Balkanlar'a vergiler hariç %50'ye varan indirim sunuyor.",
                    confidence=0.9, airlines=[{"code": "PC", "name": "Pegasus Airlines", "role": "subject"}],
                    airports=[], countries=[],
                ),
                certainty=0.9,
            ),
            risk=Outcome.not_applicable("not_a_risk"),
            campaign=Outcome.classified(
                CampaignExtraction(
                    airline_code="PC", discount_pct=50,
                    sale_starts=sale_starts, sale_ends=sale_ends,
                    travel_starts=None, travel_ends=None, markets={"regions": [], "countries": [], "cities": []},
                ),
                certainty=0.9,
            ),
        )

    monkeypatch.setattr(runner_module, "classify_article", _campaign_answer)

    source = await _source(db_session, name="Pegasus", trust=0.9)
    await _article(
        db_session, source, "https://a.example/balkanlar",
        "Balkanlar %50'ye Varan İndirimle!",
        content="Pegasus BolBol üyelerine özel Balkanlar hattında indirim kampanyası başladı.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["campaigns"] == 1
    promotion = (await db_session.execute(Promotion.__table__.select())).mappings().one()
    assert promotion["airline_code"] == "PC"
    assert promotion["airline_name"] == "Pegasus Airlines"
    assert promotion["discount_pct"] == 50
    assert promotion["sale_starts"] == sale_starts
    assert promotion["validation_state"] == "valid"
    assert promotion["confidence_band"] in ("high", "medium")
    assert promotion["event_id"] is not None


async def test_a_sale_that_closed_last_week_is_not_persisted(db_session, monkeypatch):
    """The other half of the rule the first test now depends on.

    `campaign_airline.STALE_AFTER_DAYS` is what silently turned the fixture
    above red, so the runner should also state the rule out loud: a sale whose
    window closed longer ago than the tolerance produces no row, and the run
    still counts the article as published. Without this, moving the first
    test's dates would have removed the only coverage of the boundary.
    """
    closed = date.today() - timedelta(days=STALE_AFTER_DAYS + 1)

    async def _stale_campaign(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="revenue_management", subcategory="promotion",
                    title_tr="Balkanlar %50'ye Varan İndirimle!",
                    summary_tr="Pegasus, Balkanlar'a vergiler hariç %50'ye varan indirim sunuyor.",
                    confidence=0.9, airlines=[{"code": "PC", "name": "Pegasus Airlines", "role": "subject"}],
                    airports=[], countries=[],
                ),
                certainty=0.9,
            ),
            risk=Outcome.not_applicable("not_a_risk"),
            campaign=Outcome.classified(
                CampaignExtraction(
                    airline_code="PC", discount_pct=50,
                    sale_starts=closed - timedelta(days=2), sale_ends=closed,
                    travel_starts=None, travel_ends=None,
                    markets={"regions": [], "countries": [], "cities": []},
                ),
                certainty=0.9,
            ),
        )

    monkeypatch.setattr(runner_module, "classify_article", _stale_campaign)

    source = await _source(db_session, name="Pegasus", trust=0.9)
    await _article(
        db_session, source, "https://a.example/balkanlar-kapandi",
        "Balkanlar %50'ye Varan İndirimle!",
        content="Pegasus BolBol üyelerine özel Balkanlar hattında indirim kampanyası başladı.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["campaigns"] == 0
    assert stats["published"] == 1
    assert (await db_session.execute(Promotion.__table__.select())).mappings().all() == []


async def test_an_expired_titled_campaign_is_not_persisted(db_session, monkeypatch):
    """[Expired] [Deal Alert] Save up to 30% on Economy and Business Fares --
    a real published row whose title said it was already over. Etihad Airways
    (the full two-word form) clears the gate on its own -- this test is about
    the downstream expired-title veto in campaign_airline.py, not the gate."""
    async def _with_campaign(title, content, *, topic_fragment=""):
        return ClassificationResult(
            article=Outcome.classified(
                Classification(
                    category="revenue_management", subcategory="promotion",
                    title_tr="[Expired] Ekonomi ve Business'ta %30'a Varan İndirim",
                    summary_tr="Etihad Airways'in ekonomi ve business bilet kampanyasının süresi doldu.",
                    confidence=0.8, airlines=[{"code": "EY", "name": "Etihad Airways", "role": "subject"}],
                    airports=[], countries=[],
                ),
                certainty=0.8,
            ),
            risk=Outcome.not_applicable("not_a_risk"),
            campaign=Outcome.classified(
                CampaignExtraction(
                    airline_code="EY", discount_pct=30,
                    sale_starts=date(2026, 1, 1), sale_ends=date(2026, 1, 31),
                    travel_starts=None, travel_ends=None, markets={},
                ),
                certainty=0.8,
            ),
        )

    monkeypatch.setattr(runner_module, "classify_article", _with_campaign)

    source = await _source(db_session, name="OneMileAtATime", trust=0.6)
    await _article(
        db_session, source, "https://a.example/expired",
        "[Expired] [Deal Alert] Save up to 30% on Economy and Business Fares With Etihad Airways",
        content="Etihad Airways'in ekonomi ve business sınıfı bilet kampanyası hakkında havayolu haberi.",
    )
    await db_session.commit()

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["campaigns"] == 0
    assert (await db_session.execute(Promotion.__table__.select())).mappings().all() == []
    # The event itself still exists -- it is a real (if non-campaign) news
    # item -- and its not_applicable_reasons records why no campaign followed.
    event = (await db_session.execute(NewsEvent.__table__.select())).mappings().one()
    assert event["not_applicable_reasons"]["campaign"] == "expired_title"


# --- CAMPAIGN_V2_ENABLED: the campaign-intelligence columns ----------------
#
# The flag is the whole contract here: off, this path has to behave exactly as
# it did before the campaign rebuild (every test above is the proof), and on,
# it fills the new columns and stops inserting a row the table already has.


@pytest.fixture
def campaign_v2(monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CAMPAIGN_V2_ENABLED", "true")
    yield
    get_settings.cache_clear()


def _campaign_result(**overrides) -> ClassificationResult:
    campaign = dict(
        airline_code="PC",
        discount_pct=50,
        sale_starts=date(2099, 8, 25),
        sale_ends=date(2099, 8, 27),
        travel_starts=None,
        travel_ends=None,
        markets={"regions": [], "countries": [], "cities": []},
    )
    campaign.update(overrides)
    return ClassificationResult(
        article=Outcome.classified(
            Classification(
                category="revenue_management",
                subcategory="promotion",
                title_tr="Balkanlar %50'ye Varan İndirimle!",
                summary_tr="Pegasus, Balkanlar'a %50'ye varan indirim sunuyor.",
                confidence=0.9,
                airlines=[{"code": "PC", "name": "Pegasus Airlines", "role": "subject"}],
                airports=[],
                countries=[],
            ),
            certainty=0.9,
        ),
        risk=Outcome.not_applicable("not_a_risk"),
        campaign=Outcome.classified(CampaignExtraction(**campaign), certainty=0.9),
    )


async def _seed_campaign_article(db) -> None:
    source = await _source(db, name="Pegasus", trust=0.9)
    await _article(
        db,
        source,
        "https://a.example/balkanlar",
        "Balkanlar %50'ye Varan İndirimle!",
        content="Pegasus Balkanlar hattında indirim kampanyası başlattı.",
    )
    await db.commit()


async def test_the_flag_asks_the_model_for_the_campaign_fields_and_stores_them(
    db_session, monkeypatch, campaign_v2
):
    seen: dict = {}

    async def _answer(title, content, *, topic_fragment=""):
        seen["fragment"] = topic_fragment
        return _campaign_result(
            campaign_type="FLASH_SALE",
            business_class_hint="ACTIVE_CAMPAIGN",
            origin="İstanbul",
            destination="Londra",
        )

    monkeypatch.setattr(runner_module, "classify_article", _answer)
    await _seed_campaign_article(db_session)

    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["campaigns"] == 1
    assert "business_class_hint" in seen["fragment"], "the topic hook carries the ask"

    promotion = (await db_session.execute(Promotion.__table__.select())).mappings().one()
    assert promotion["campaign_type"] == "FLASH_SALE"
    # The rule layer's verdict, not the model's hint -- they agree here, and
    # when they do not, validate_campaign wins.
    assert promotion["business_class"] == "ACTIVE_CAMPAIGN"
    assert promotion["classification_reason"]
    assert promotion["route_scope"] == "CITY_PAIR", "two cities are not an OND"
    assert promotion["ond"] is None
    assert promotion["first_seen_at"] is not None
    assert promotion["last_seen_at"] is not None


async def test_a_campaign_the_table_already_has_is_merged_not_inserted_again(
    db_session, monkeypatch, campaign_v2
):
    """The documented gap in this path: every other write path asked
    promo_dedup before inserting and this one did not, so the airline's own
    page and a news report about the same campaign each drew their own bar."""
    async def _answer(title, content, *, topic_fragment=""):
        return _campaign_result()

    monkeypatch.setattr(runner_module, "classify_article", _answer)

    existing = Promotion(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Balkanlar %50'ye Varan İndirimle!",
        summary_tr="",
        url="https://www.flypgs.com/kampanyalar/balkanlar",
        source_name="Pegasus kampanya sayfası",
        detected_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(existing)
    await db_session.commit()
    existing_id = existing.id

    await _seed_campaign_article(db_session)
    stats = await run_pipeline_v2(db_session, limit=10)

    assert stats["campaigns"] == 1
    rows = (await db_session.execute(Promotion.__table__.select())).mappings().all()
    assert len(rows) == 1, "one campaign, one row"
    assert rows[0]["id"] == existing_id
    assert rows[0]["discount_pct"] == 50, "the article's reading enriched the row"
    assert rows[0]["business_class"] == "ACTIVE_CAMPAIGN"
    assert rows[0]["url"] == "https://www.flypgs.com/kampanyalar/balkanlar", (
        "the airline's own page keeps its canonical URL"
    )

    # Both pages are on the record, at the tier each of them earns: the
    # carrier's campaign page is official, and a news outlet reporting on it is
    # secondary reporting about somebody else's campaign, however good it is.
    sources = (
        await db_session.execute(
            CampaignSource.__table__.select().order_by(CampaignSource.__table__.c.url)
        )
    ).mappings().all()
    assert [(s["url"], s["source_tier"]) for s in sources] == [
        ("https://a.example/balkanlar", "secondary"),
        ("https://www.flypgs.com/kampanyalar/balkanlar", "official"),
    ]
    # ...and what the article added to the row is a version row, not a silent
    # overwrite of the page's own reading.
    versions = (
        await db_session.execute(CampaignVersion.__table__.select())
    ).mappings().all()
    assert len(versions) == 1
    assert versions[0]["version_no"] == 1
    assert versions[0]["changed_fields"]["discount_pct"] == {"previous": None, "new": 50}
    assert versions[0]["source_url"] == "https://a.example/balkanlar"
    assert rows[0]["last_changed_at"] is not None


async def test_a_campaign_written_from_an_article_records_the_article_as_its_source(
    db_session, monkeypatch, campaign_v2
):
    """N>=1 from the moment a row exists -- and no version row for creating it,
    because a version records a change and there is nothing yet to change."""
    async def _answer(title, content, *, topic_fragment=""):
        return _campaign_result()

    monkeypatch.setattr(runner_module, "classify_article", _answer)
    await _seed_campaign_article(db_session)

    await run_pipeline_v2(db_session, limit=10)

    promotion = (await db_session.execute(Promotion.__table__.select())).mappings().one()
    sources = (await db_session.execute(CampaignSource.__table__.select())).mappings().all()
    assert len(sources) == 1
    assert sources[0]["promotion_id"] == promotion["id"]
    assert sources[0]["url"] == promotion["url"]
    assert sources[0]["source_tier"] == "secondary"
    assert sources[0]["page_published_at"] is not None
    assert (
        await db_session.execute(CampaignVersion.__table__.select())
    ).mappings().all() == []


async def test_a_carriers_own_feed_is_a_newsroom_not_a_campaign_page(
    db_session, monkeypatch, campaign_v2
):
    """`sources.tier == "official"` means the carrier's own channel. That
    outranks the trade press and still does not outrank the page that actually
    sells the fare and states its terms."""
    async def _answer(title, content, *, topic_fragment=""):
        return _campaign_result()

    monkeypatch.setattr(runner_module, "classify_article", _answer)
    source = Source(
        name="Pegasus Basın Odası",
        url="https://www.flypgs.com/basin-odasi/feed",
        source_type="rss",
        trust_weight=0.9,
        tier="official",
    )
    db_session.add(source)
    await db_session.flush()
    await _article(
        db_session,
        source,
        "https://www.flypgs.com/basin-odasi/balkanlar",
        "Balkanlar %50'ye Varan İndirimle!",
        content="Pegasus Balkanlar hattında indirim kampanyası başlattı.",
    )
    await db_session.commit()

    await run_pipeline_v2(db_session, limit=10)

    sources = (await db_session.execute(CampaignSource.__table__.select())).mappings().all()
    assert [s["source_tier"] for s in sources] == ["newsroom"]


async def test_with_the_flag_off_the_new_columns_stay_null(db_session, monkeypatch):
    """A legacy-shaped row: classified by the rules that predate the rebuild,
    and carrying NULL in every column the rebuild added -- which is what "not
    classified" has to look like, distinct from "classified as nothing"."""
    async def _answer(title, content, *, topic_fragment=""):
        assert topic_fragment == "", "flag off means the prompt is untouched"
        return _campaign_result(campaign_type="FLASH_SALE", origin="İstanbul")

    monkeypatch.setattr(runner_module, "classify_article", _answer)
    await _seed_campaign_article(db_session)

    await run_pipeline_v2(db_session, limit=10)

    promotion = (await db_session.execute(Promotion.__table__.select())).mappings().one()
    assert promotion["campaign_type"] is None
    assert promotion["business_class"] is None
    assert promotion["route_scope"] is None
    assert promotion["classification_reason"] is None
    assert promotion["first_seen_at"] is None
