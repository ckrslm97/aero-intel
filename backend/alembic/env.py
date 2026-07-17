import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.db import Base, normalize_database_url

import app.models  # noqa: F401  (imports all models so Alembic's autogenerate can see them)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()

# Managed-Postgres URLs (Neon et al) carry libpq-only params asyncpg rejects, so
# they go through the same normalization the app uses -- see app/core/db.py.
# The URL is then used directly rather than via config.set_main_option(), which
# would run it through configparser interpolation and choke on a '%' in the
# password.
DATABASE_URL, _CONNECT_ARGS = normalize_database_url(settings.database_url)

# Migrations are meant to run against the direct (unpooled) endpoint, but a
# pooled URL is what Neon shows first -- so disable asyncpg's prepared-statement
# cache, which pgbouncer's transaction mode can't serve. One-shot DDL, so the
# cache buys nothing anyway.
_CONNECT_ARGS = {**_CONNECT_ARGS, "statement_cache_size": 0}


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args=_CONNECT_ARGS,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
