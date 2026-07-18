"""add fund tables for the /invest module

funds + fund_prices + fund_holdings + fund_allocations + fund_analyses:
prices and holdings carry a per-row verification_status (verified /
official_single_source / single_source / discrepancy) so the UI can badge
exactly how each number was corroborated -- unverified data is labeled, never
hidden or dressed up.

Revision ID: c47d2a91f3b8
Revises: b31f7a9c1e02
Create Date: 2026-07-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c47d2a91f3b8"
down_revision = "b31f7a9c1e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False, unique=True),
        sa.Column("market", sa.String(5), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("currency", sa.String(5), nullable=False),
        sa.Column("issuer", sa.String(120), nullable=False, server_default=""),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("expense_ratio", sa.Float(), nullable=True),
        sa.Column("aum", sa.Float(), nullable=True),
        sa.Column("aum_as_of", sa.Date(), nullable=True),
        sa.Column("metadata_source", sa.String(100), nullable=False, server_default=""),
        sa.Column("metadata_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_funds_symbol", "funds", ["symbol"])

    op.create_table(
        "fund_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="single_source"),
    )
    op.create_index("ix_fund_prices_fund_as_of", "fund_prices", ["fund_id", "as_of"])

    op.create_table(
        "fund_holdings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("holding_name", sa.String(300), nullable=False),
        sa.Column("weight_pct", sa.Float(), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="single_source"),
        sa.Column("is_top10_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_fund_holdings_fund_as_of", "fund_holdings", ["fund_id", "as_of"])

    op.create_table(
        "fund_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("weight_pct", sa.Float(), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
    )
    op.create_index("ix_fund_allocations_fund_as_of", "fund_allocations", ["fund_id", "as_of"])

    op.create_table(
        "fund_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id", ondelete="CASCADE"), nullable=True),
        sa.Column("analysis_date", sa.Date(), nullable=False),
        sa.Column("body_tr", sa.Text(), nullable=False),
        sa.Column("outlook", sa.String(20), nullable=False, server_default="neutral"),
        sa.Column("provider", sa.String(30), nullable=False, server_default="heuristic"),
        sa.Column("input_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("scope", "fund_id", "analysis_date", name="uq_fund_analyses_scope_fund_date"),
    )


def downgrade() -> None:
    op.drop_table("fund_analyses")
    op.drop_table("fund_allocations")
    op.drop_table("fund_holdings")
    op.drop_table("fund_prices")
    op.drop_table("funds")
