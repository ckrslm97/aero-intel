"""Keeps Article.search_vector in sync -- called at ingestion (title+body) and
again at enrichment (title+headline+summary+tags, once those exist)."""
import uuid

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article


async def index_article_text(db: AsyncSession, article_id: uuid.UUID, text: str) -> None:
    await db.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(search_vector=func.to_tsvector("english", text))
    )
