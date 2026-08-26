"""Postgres FTS backs search, and it is the only backend.

The Elasticsearch stub that used to sit beside this file was never a real
implementation, so `ELASTICSEARCH_URL` selected nothing and the settings key
only invited someone to believe otherwise. Both are gone. Reintroducing a
second backend means writing one and wiring the choice here deliberately.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.base import SearchBackend
from app.search.postgres_fts import PostgresFtsBackend


def get_search_backend(db: AsyncSession) -> SearchBackend:
    return PostgresFtsBackend(db)
