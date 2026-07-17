"""Async SQLAlchemy engine/session plumbing.

Runs in two shapes:

* a long-lived process (local dev, Docker, a GitHub Actions job) -- normal
  client-side connection pool;
* a serverless function (Vercel) talking to a pooled Neon endpoint -- no
  client-side pool and no server-side prepared statements, because the process
  is frozen between requests and pgbouncer hands each transaction a different
  backend. See `_engine_kwargs()`.
"""
import os
from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# Vercel sets VERCEL=1 in every function environment.
IS_SERVERLESS = bool(os.environ.get("VERCEL"))

# libpq-only query params. asyncpg parses `sslmode` when *it* owns the DSN, but
# SQLAlchemy owns the URL here and forwards unknown query params straight to
# asyncpg.connect() as kwargs -- which raises TypeError. So `sslmode` is
# translated to asyncpg's `ssl` kwarg (it accepts the same libpq strings) and
# the rest are dropped. Managed providers (Neon, Supabase) ship these params in
# the connection string they hand you, so a copy-pasted URL must Just Work.
_DROPPED_LIBPQ_PARAMS = ("channel_binding",)


def normalize_database_url(raw_url: str) -> tuple[str, dict]:
    """Turn a copy-pasted managed-Postgres URL into (SQLAlchemy URL, connect_args).

    Fixes the three things that differ from what SQLAlchemy+asyncpg accept: the
    `postgres://` scheme alias, a missing `+asyncpg` driver, and libpq-only
    query params. The returned connect_args carry the SSL intent `sslmode`
    expressed, so nothing is silently downgraded.
    """
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    connect_args: dict = {}

    sslmode = query.pop("sslmode", None)
    if sslmode:
        # asyncpg's `ssl` kwarg parses libpq sslmode strings ("require",
        # "verify-full", ...) -- a faithful 1:1 translation, not a guess.
        connect_args["ssl"] = sslmode
    for param in _DROPPED_LIBPQ_PARAMS:
        query.pop(param, None)

    cleaned = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return cleaned, connect_args


def _engine_kwargs(connect_args: dict) -> dict:
    if not IS_SERVERLESS:
        return {"pool_pre_ping": True, "connect_args": connect_args}

    # Serverless: the platform freezes the process between invocations, so a
    # client-side pool would pin Neon connections it can never health-check --
    # let the Neon pooler do the pooling instead.
    #
    # The three statement settings are the documented pgbouncer-transaction-mode
    # recipe: pgbouncer may route consecutive statements to different backends,
    # so server-side prepared statements either miss or collide by name.
    return {
        "poolclass": NullPool,
        "connect_args": {
            **connect_args,
            "statement_cache_size": 0,  # asyncpg's own cache
            "prepared_statement_cache_size": 0,  # SQLAlchemy's asyncpg adapter cache
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    }


DATABASE_URL, _CONNECT_ARGS = normalize_database_url(settings.database_url)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    **_engine_kwargs(_CONNECT_ARGS),
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
