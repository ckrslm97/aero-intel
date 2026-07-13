"""Cross-source confidence scoring for a canonical article + its duplicate group."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article


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
