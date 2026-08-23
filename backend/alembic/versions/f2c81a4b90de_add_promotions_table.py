"""add promotions table

Airline campaigns need their own table rather than a sixth aviation_events
type: aviation_events has no airline column (it is keyed on city/country,
because an airshow happens somewhere while a campaign is run by someone), and
its five types are already mapped one-to-one onto the five --chart-* tokens.

Every date column is nullable. Press coverage of a campaign is routinely vague
about its window, and a NOT NULL here would force the extractor to invent
dates that would then be drawn as if they had been measured.

`url` carries the unique constraint, matching aviation_events: it is the
idempotency key for both the scraper and the article-derived extractor, so a
re-run updates in place instead of duplicating.

Revision ID: f2c81a4b90de
Revises: b4357df7d0de
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2c81a4b90de"
down_revision = "b4357df7d0de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("airline_code", sa.String(6), nullable=False),
        sa.Column("airline_name", sa.String(120), nullable=False),
        sa.Column("title_tr", sa.String(300), nullable=False),
        sa.Column("summary_tr", sa.Text(), nullable=False, server_default=""),
        sa.Column("discount_pct", sa.Integer(), nullable=True),
        sa.Column("markets", sa.String(500), nullable=True),
        sa.Column("sale_starts", sa.Date(), nullable=True),
        sa.Column("sale_ends", sa.Date(), nullable=True),
        sa.Column("travel_starts", sa.Date(), nullable=True),
        sa.Column("travel_ends", sa.Date(), nullable=True),
        sa.Column("url", sa.String(500), nullable=False, unique=True),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("region", sa.String(30), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_promotions_airline_code", "promotions", ["airline_code"])
    op.create_index("ix_promotions_sale_starts", "promotions", ["sale_starts"])
    op.create_index("ix_promotions_region", "promotions", ["region"])
    op.create_index("ix_promotions_detected_at", "promotions", ["detected_at"])


def downgrade() -> None:
    op.drop_table("promotions")
