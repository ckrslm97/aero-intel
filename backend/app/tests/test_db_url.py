"""The connection string a managed provider hands you is not what SQLAlchemy +
asyncpg accept. These pin the translation, because the failure mode only shows
up against a real cloud database (a copy-pasted Neon URL raising TypeError on
an unexpected 'sslmode' kwarg).
"""
from app.core.db import normalize_database_url

NEON_POOLED = (
    "postgresql://neondb_owner:npg_pw@ep-x-pooler.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_local_dev_url_is_left_alone():
    url, connect_args = normalize_database_url("postgresql+asyncpg://localhost:5432/aerointel")
    assert url == "postgresql+asyncpg://localhost:5432/aerointel"
    assert connect_args == {}


def test_neon_url_gets_driver_and_sheds_libpq_params():
    url, connect_args = normalize_database_url(NEON_POOLED)
    assert url == (
        "postgresql+asyncpg://neondb_owner:npg_pw@ep-x-pooler.eu-central-1.aws.neon.tech/neondb"
    )
    # sslmode is preserved as intent, not dropped: asyncpg's `ssl` kwarg parses
    # the same libpq strings.
    assert connect_args == {"ssl": "require"}


def test_postgres_scheme_alias_is_upgraded():
    url, _ = normalize_database_url("postgres://u:p@host/db")
    assert url.startswith("postgresql+asyncpg://")


def test_sslmode_verify_full_is_passed_through_verbatim():
    _, connect_args = normalize_database_url("postgresql://u:p@h/db?sslmode=verify-full")
    assert connect_args == {"ssl": "verify-full"}


def test_unrelated_query_params_survive():
    url, _ = normalize_database_url("postgresql://u:p@h/db?application_name=aerointel")
    assert "application_name=aerointel" in url
