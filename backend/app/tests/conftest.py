"""Test fixtures backed by a real Postgres database (`aerointel_test`) so models
using Postgres-specific types (UUID, JSONB, full-text search) behave exactly as
in production -- SQLite would silently diverge on these.

The engine is created fresh per test (not session-scoped) so it always lives in
the same event loop as the test that uses it -- pytest-asyncio's per-function
event loops make a shared engine across tests a source of "another operation is
in progress" asyncpg errors.
"""
import os
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base

# Overridable so CI (which needs credentials for its Postgres service
# container) doesn't have to match the trust-auth-friendly local default.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/aerointel_test"
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class _QueryCounter:
    """How many statements a block of code actually sent to Postgres.

    Written because "this should be faster" is not a measurement and this repo
    does not accept one. A query count is the thing that regresses invisibly:
    the FX board cost five round trips per currency pair, and the commit that
    added GBP/TRY added five more without anyone deciding to. A test that
    asserts a NUMBER is what makes that a failure instead of a slow page.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)


@pytest.fixture
def query_counter(db_session):
    """`with query_counter() as counted: ...` -> `counted.count`."""

    @contextmanager
    def _counting():
        counter = _QueryCounter()
        engine = db_session.bind.sync_engine

        def before(conn, cursor, statement, parameters, context, executemany):
            counter.statements.append(statement)

        event.listen(engine, "before_cursor_execute", before)
        try:
            yield counter
        finally:
            event.remove(engine, "before_cursor_execute", before)

    return _counting
