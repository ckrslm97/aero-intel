"""Faz 13/K8: marking pre-validation campaign rows as superseded rather than
destroying them -- see promo_dedup.mark_legacy_campaigns_superseded."""
from datetime import datetime, timezone

from app.models.promotion import Promotion
from app.pipeline.promo_dedup import mark_legacy_campaigns_superseded

NOW = datetime.now(timezone.utc)


def _promotion(url, *, validation_state=None, superseded_at=None) -> Promotion:
    return Promotion(
        airline_code="TK",
        airline_name="Turkish Airlines",
        title_tr="Kampanya",
        url=url,
        source_name="thy.com",
        detected_at=NOW,
        validation_state=validation_state,
        superseded_at=superseded_at,
    )


async def test_marks_rows_with_no_validation_state_as_superseded(db_session):
    legacy = _promotion("https://example.com/legacy")
    db_session.add(legacy)
    await db_session.commit()

    result = await mark_legacy_campaigns_superseded(db_session)

    assert result == {"marked_superseded": 1}
    await db_session.refresh(legacy)
    assert legacy.superseded_at is not None


async def test_leaves_validated_rows_alone_even_when_incomplete(db_session):
    """validation_state="incomplete" is a real, still-served state (a row
    the new pipeline saw and validated, just missing a sale window) -- not
    the same thing as never having been validated at all."""
    incomplete = _promotion("https://example.com/incomplete", validation_state="incomplete")
    valid = _promotion("https://example.com/valid", validation_state="valid")
    db_session.add_all([incomplete, valid])
    await db_session.commit()

    result = await mark_legacy_campaigns_superseded(db_session)

    assert result == {"marked_superseded": 0}
    await db_session.refresh(incomplete)
    await db_session.refresh(valid)
    assert incomplete.superseded_at is None
    assert valid.superseded_at is None


async def test_is_idempotent(db_session):
    legacy = _promotion("https://example.com/legacy")
    db_session.add(legacy)
    await db_session.commit()

    first = await mark_legacy_campaigns_superseded(db_session)
    second = await mark_legacy_campaigns_superseded(db_session)

    assert first == {"marked_superseded": 1}
    assert second == {"marked_superseded": 0}
