"""add hot-path indexes and articles.word_count

Measured on production before this migration: GET /articles took 2.8s warm
while GET /health took 0.26s -- the latency was all query work. The `articles`
table had no index on any column the newspaper filters or sorts by, so every
filter click sequentially scanned it.

word_count exists so the article list no longer has to transfer raw_content
(the full scraped body) out of Postgres just to compute a reading time that is
then thrown away; the column is filled at ingest and backfilled below.

Indexes are created CONCURRENTLY (outside a transaction) so a long build on a
growing table never locks writes on the live database.

Revision ID: d5a81c3f76e4
Revises: c47d2e91ab53
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "d5a81c3f76e4"
down_revision = "c47d2e91ab53"
branch_labels = None
depends_on = None

# (name, table, definition) -- definition is everything after ON <table>
INDEXES: list[tuple[str, str, str]] = [
    # The newspaper's default query: not-duplicate, newest first.
    (
        "ix_articles_live_recency",
        "articles",
        "(published_at DESC NULLS LAST, fetched_at DESC) WHERE is_duplicate = false",
    ),
    # The archive's day filter and /articles/daily-counts, which group on
    # coalesce(published_at, fetched_at) -- an expression index is the only
    # thing that can serve it.
    (
        "ix_articles_day_expr",
        "articles",
        "((coalesce(published_at, fetched_at))) WHERE is_duplicate = false",
    ),
    ("ix_articles_source_id", "articles", "(source_id)"),
    # The airline filter joins from entity -> article; the primary key is
    # (article_id, entity_id), which cannot serve that direction.
    ("ix_article_entities_entity", "article_entities", "(entity_id, article_id)"),
    # Entity.code had no index at all despite `code = ?` / `code IN (...)`
    # running on every Ana Rakipler click.
    ("ix_entities_type_code", "entities", "(entity_type, code)"),
    # Category + subcategory + region arrive together from the filter rows;
    # three separate single-column indexes force a bitmap AND.
    (
        "ix_enrichment_cat_sub_region",
        "article_enrichment",
        "(category, subcategory, region)",
    ),
    ("ix_kpis_metric_primary_asof", "kpis", "(metric_key, is_primary, as_of DESC)"),
]


def upgrade() -> None:
    op.add_column("articles", sa.Column("word_count", sa.Integer(), nullable=True))
    # Backfill in one pass; raw_content is already in the row so this is a
    # single sequential scan, not a per-row round trip.
    op.execute(
        "UPDATE articles SET word_count = array_length(regexp_split_to_array("
        "trim(coalesce(raw_content, '')), '\\s+'), 1) "
        "WHERE word_count IS NULL"
    )

    # CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        for name, table, definition in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _table, _definition in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.drop_column("articles", "word_count")
