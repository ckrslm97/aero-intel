"""Cross-source confidence scoring for a canonical article + its duplicate group."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article

#: The formula below at its arithmetic minimum: 0.4 + 0.15 * 0 + 0.3 * 0.
#:
#: A stored `confidence_score` STRICTLY BELOW this cannot have come out of
#: `compute_confidence` at all, which makes it the one reliable marker of a row
#: the confidence pass never touched: ArticleEnrichment.confidence_score is a
#: NOT NULL column defaulting to 0.0, so "nobody measured this" and "measured,
#: scored zero" arrive in the database as the same value and only the floor
#: tells them apart.
#:
#: Lives here, beside the formula, because two surfaces read it for opposite
#: purposes and neither may drift from the arithmetic: the Risk Radarı's gate
#: (app/api/v1/risks.py) publishes such rows rather than treating them as
#: measured-and-weak, and the article schema (app/schemas/article.py) refuses
#: to print a percentage for them.
CONFIDENCE_FORMULA_MIN = 0.4


def measured_confidence(value: float | None) -> float | None:
    """The stored score if the confidence pass actually produced it, else None.

    THE null-out rule, in one place, because it was applied on one surface and
    forgotten on the next: the analysis drawer stopped printing "%0 güven" for
    an article nobody had scored (app/schemas/article.py) while the risk
    verification table went on rendering "0.00" for that very same article --
    directly above its own caption reading "ölçülmedi, kapı yargılamadı". Two
    surfaces, one column, two answers.

    A genuinely scored low value (0.535 is the seeded catalogue's single-source
    floor) is above the floor and travels through untouched.
    """
    if value is None or value < CONFIDENCE_FORMULA_MIN:
        return None
    return value


async def compute_confidence(db: AsyncSession, article: Article) -> tuple[int, float]:
    """Confidence rises with the number of independent sources corroborating a
    story and their trust weight -- a simple, auditable heuristic (not a
    statistical model): one trusted source lands around ~0.6-0.7; three
    independent sources covering the same story pushes it above ~0.9.
    """
    result = await db.execute(
        select(Article)
        .options(selectinload(Article.source))
        .where((Article.id == article.id) | (Article.duplicate_of_id == article.id))
    )
    group = list(result.scalars().all())

    trust_by_source: dict[uuid.UUID, float] = {a.source_id: a.source.trust_weight for a in group}
    corroborating_count = len(trust_by_source)
    avg_trust = sum(trust_by_source.values()) / corroborating_count if trust_by_source else 0.5

    confidence = 0.4 + 0.15 * (corroborating_count - 1) + 0.3 * avg_trust
    return corroborating_count, round(min(1.0, max(0.0, confidence)), 3)
