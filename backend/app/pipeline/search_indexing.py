"""Keeps Article.search_vector in sync -- called at ingestion (title+body) and
again at enrichment and translation, once the derived text exists.

The indexed text now includes `headline_tr` and `summary_tr`. It did not, and
the consequence was that /search -- on a Turkish-language paper -- could not
find a Turkish word: the vector held only the English title, headline and
summary, so "yakıt" or "kapasite" matched nothing while "fuel" and "capacity"
worked fine.

Still `to_tsvector('english', ...)`, deliberately, and that is a KNOWN
limitation rather than an oversight. The English configuration stems English
and leaves Turkish words as literal tokens, so Turkish now matches VERBATIM:
"yakıt" finds "yakıt", but "yakıta" and "yakıtın" do not, and neither does a
plural. Postgres ships no Turkish snowball dictionary, so proper Turkish
stemming means installing/creating a text-search configuration in the database
-- a migration with an operational prerequisite, which is a separate change
from putting the Turkish text in the index at all. Verbatim matching is a large
improvement over no matching; it is not the finished job.
"""
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
