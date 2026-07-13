"""Postgres FTS backs search unconditionally in this build. ELASTICSEARCH_URL is
reserved for a future ElasticsearchBackend (see elasticsearch.py) -- it isn't
wired to this selection yet, since that backend isn't a real implementation and
silently switching to it would be worse than the Postgres default.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.base import SearchBackend
from app.search.postgres_fts import PostgresFtsBackend


def get_search_backend(db: AsyncSession) -> SearchBackend:
    return PostgresFtsBackend(db)
