"""Test fixtures backed by a real Postgres database (`aerointel_test`) so models
using Postgres-specific types (UUID, JSONB, full-text search) behave exactly as
in production -- SQLite would silently diverge on these.

The engine is created fresh per test (not session-scoped) so it always lives in
the same event loop as the test that uses it -- pytest-asyncio's per-function
event loops make a shared engine across tests a source of "another operation is
in progress" asyncpg errors.
"""
import os

import pytest_asyncio
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
