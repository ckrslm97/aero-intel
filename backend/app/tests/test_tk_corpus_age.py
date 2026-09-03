"""The BİZ page's collection date is read off the corpus, not typed into it.

The footnote under the passenger-review block said "Toplama tarihi: 19 Temmuz
2026" as a literal string in the component. It was correct on the day someone
typed it and wrong on every day after, including after each curation pass added
rows -- a page about what passengers are saying, dated by hand. The rows carry
the answer, so `review_stats` returns it.

Both directions: the date is the newest row's, and an empty corpus says
nothing rather than saying today.
"""
from datetime import datetime, timedelta, timezone

from app.models.tk_review import TkReview
from app.services.tk_service import review_stats


async def _review(db, *, key: str, created_at: datetime | None = None) -> TkReview:
    row = TkReview(
        source_name="Skytrax",
        url="https://example.com/tk",
        dedupe_key=key,
        excerpt="Kabin ekibi ilgiliydi.",
        sentiment="positive",
        themes=["cabin_crew"],
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    await db.flush()
    return row


async def test_collected_through_is_the_newest_rows_own_timestamp(db_session):
    newest = datetime.now(timezone.utc) - timedelta(hours=5)
    await _review(db_session, key="old", created_at=newest - timedelta(days=40))
    await _review(db_session, key="new", created_at=newest)
    await db_session.commit()

    stats = await review_stats(db_session)

    assert stats["collected_through"] == newest.isoformat()
    assert stats["review_count"] == 2


async def test_an_empty_corpus_states_no_collection_date(db_session):
    """NULL, not today: nothing has been collected, and "collected up to now"
    would be a claim about a table with no rows in it."""
    stats = await review_stats(db_session)

    assert stats["review_count"] == 0
    assert stats["collected_through"] is None


async def test_a_later_curation_pass_moves_the_date(db_session):
    """The whole point: the sentence follows the corpus instead of a commit."""
    first = datetime.now(timezone.utc) - timedelta(days=30)
    await _review(db_session, key="first", created_at=first)
    await db_session.commit()
    before = await review_stats(db_session)

    later = datetime.now(timezone.utc)
    await _review(db_session, key="second", created_at=later)
    await db_session.commit()
    after = await review_stats(db_session)

    assert before["collected_through"] == first.isoformat()
    assert after["collected_through"] == later.isoformat()
