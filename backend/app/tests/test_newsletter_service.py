from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.article import Article, ArticleEnrichment
from app.models.edition import Edition, EditionArticle
from app.models.email_delivery import EmailDelivery
from app.models.source import Source
from app.models.subscriber import Subscriber
from app.services import newsletter_service


async def _seed_edition(db_session) -> Edition:
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    article = Article(
        source_id=source.id,
        url="https://example.com/a",
        title="Story",
        raw_content="body",
        fetched_at=datetime.now(timezone.utc),
        content_hash="hash-a",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Story headline",
            summary="Story summary.",
            category="general",
            importance_score=0.5,
            confidence_score=0.6,
            corroborating_source_count=1,
        )
    )
    edition = Edition(edition_date=date(2026, 7, 12), headline="Story headline", status="published")
    db_session.add(edition)
    await db_session.flush()
    db_session.add(EditionArticle(edition_id=edition.id, article_id=article.id, section="top_story", rank=0))
    await db_session.commit()

    from sqlalchemy.orm import selectinload

    result = await db_session.execute(
        select(Edition)
        .options(
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.source),
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.enrichment),
        )
        .where(Edition.id == edition.id)
    )
    return result.scalar_one()


async def test_send_newsletter_marks_delivery_sent(db_session, monkeypatch):
    subscriber = Subscriber(email="reader@example.com")
    db_session.add(subscriber)
    await db_session.commit()

    edition = await _seed_edition(db_session)

    sent_to = []

    async def fake_send_email(to_email, subject, html_body):
        sent_to.append(to_email)

    monkeypatch.setattr(newsletter_service, "send_email", fake_send_email)

    stats = await newsletter_service.send_newsletter_for_edition(db_session, edition)

    assert stats == {"sent": 1, "failed": 0, "skipped": 0}
    assert sent_to == ["reader@example.com"]

    result = await db_session.execute(select(EmailDelivery))
    delivery = result.scalar_one()
    assert delivery.status == "sent"
    assert delivery.attempts == 1
    assert delivery.sent_at is not None


async def test_send_newsletter_retries_failed_deliveries_until_max_attempts(db_session, monkeypatch):
    subscriber = Subscriber(email="reader@example.com")
    db_session.add(subscriber)
    await db_session.commit()

    edition = await _seed_edition(db_session)

    async def always_fails(to_email, subject, html_body):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(newsletter_service, "send_email", always_fails)

    for _ in range(newsletter_service.MAX_ATTEMPTS):
        await newsletter_service.send_newsletter_for_edition(db_session, edition)

    result = await db_session.execute(select(EmailDelivery))
    delivery = result.scalar_one()
    assert delivery.status == "failed"
    assert delivery.attempts == newsletter_service.MAX_ATTEMPTS
    assert "SMTP unavailable" in delivery.last_error

    # one more run should skip it -- attempts already at the cap
    stats = await newsletter_service.send_newsletter_for_edition(db_session, edition)
    assert stats == {"sent": 0, "failed": 0, "skipped": 1}
