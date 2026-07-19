"""add tk_reviews table and insight_digests.topic

tk_reviews: agent-curated passenger reviews about Turkish Airlines for the
BİZ page (short excerpts + source links, fixed theme vocabulary).

insight_digests.topic: the digest table now stores more than the daily
insights paragraph -- the BİZ page's review synthesis lives in the same table
under topic='tk_reviews' -- so uniqueness moves from (digest_date) to
(digest_date, topic).

Revision ID: c47d2e91ab53
Revises: b31f7a9c1e02
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c47d2e91ab53"
down_revision = "b31f7a9c1e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tk_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("url", sa.String(600), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("author", sa.String(120), nullable=True),
        sa.Column("route", sa.String(60), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("excerpt_tr", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=False),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tk_reviews_review_date", "tk_reviews", ["review_date"])
    op.create_index("ix_tk_reviews_sentiment", "tk_reviews", ["sentiment"])

    op.add_column(
        "insight_digests",
        sa.Column("topic", sa.String(20), nullable=False, server_default="daily"),
    )
    # Uniqueness moves from the bare date to (date, topic). The old constraint
    # was created by column-level unique=True, so it carries Postgres's
    # auto-generated name.
    op.drop_constraint("insight_digests_digest_date_key", "insight_digests", type_="unique")
    op.create_unique_constraint(
        "uq_insight_digests_digest_date_topic", "insight_digests", ["digest_date", "topic"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_insight_digests_digest_date_topic", "insight_digests", type_="unique")
    op.create_unique_constraint(
        "insight_digests_digest_date_key", "insight_digests", ["digest_date"]
    )
    op.drop_column("insight_digests", "topic")
    op.drop_table("tk_reviews")
