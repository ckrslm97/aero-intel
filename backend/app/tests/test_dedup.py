from datetime import datetime, timezone

from app.models.article import Article
from app.models.source import Source
from app.pipeline.dedup import deduplicate_new_articles

SHARED_BODY = (
    "This report is produced by the network operations team and distributed "
    "to members on a recurring schedule. It summarizes recent activity across "
    "the network and highlights notable trends for stakeholders to review."
)


async def _seed(db_session, canonical_title: str, new_title: str) -> Article:
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    canonical = Article(
        source_id=source.id,
        url="https://example.com/canonical",
        title=canonical_title,
        raw_content=SHARED_BODY,
        fetched_at=now,
        content_hash="canonical-hash",
        status="deduped",
    )
    new = Article(
        source_id=source.id,
        url="https://example.com/new",
        title=new_title,
        raw_content=SHARED_BODY,
        fetched_at=now,
        content_hash="new-hash",
        status="new",
    )
    db_session.add_all([canonical, new])
    await db_session.flush()
    return new


async def test_paraphrased_same_story_is_marked_duplicate(db_session):
    new = await _seed(
        db_session,
        canonical_title="Delta Air Lines launches new nonstop route to Tokyo",
        new_title="Delta launches nonstop Tokyo route",
    )

    await deduplicate_new_articles(db_session)
    await db_session.refresh(new)

    assert new.status == "duplicate"
    assert new.is_duplicate is True


async def test_recurring_report_differing_only_by_number_is_not_duplicate(db_session):
    new = await _seed(
        db_session,
        canonical_title="EUROCONTROL European Aviation Overview 2026 - Week 25",
        new_title="EUROCONTROL European Aviation Overview 2026 - Week 27",
    )

    await deduplicate_new_articles(db_session)
    await db_session.refresh(new)

    assert new.status == "deduped"
    assert new.is_duplicate is False


async def test_shared_boilerplate_with_unrelated_title_is_not_duplicate(db_session):
    new = await _seed(
        db_session,
        canonical_title="HindSight - Winter 2024",
        new_title="EUROCONTROL European Aviation Overview 2026 - Week 27",
    )

    await deduplicate_new_articles(db_session)
    await db_session.refresh(new)

    assert new.status == "deduped"
    assert new.is_duplicate is False
