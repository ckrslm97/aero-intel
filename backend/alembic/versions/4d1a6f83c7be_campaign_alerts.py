"""campaign alerts

Migration B of the campaign-intelligence rebuild, and the only one that adds a
table nothing else reads from. `campaign_alerts` is a notification log: one row
per thing a revenue desk should be told once, with `dedupe_key` UNIQUE as the
mechanism that makes "once" true across a cron that this repo measures at
2-2.75 hours late and that deliberately calls the generator from two separate
workflows.

The UNIQUE constraint is therefore not a data-hygiene nicety -- it is the
feature. Alert generation is written as INSERT ... ON CONFLICT DO NOTHING
against it, so a second run of the same day recomputes the same keys and writes
nothing, and a *missed* run still catches every alert on the next pass because
each key's bucket is a property of the campaign (its first-seen day, its
version number, its sale_ends date) rather than of the moment the job ran.

New table only, no change to any existing one, so an old worker running against
the new schema mid-deploy is unaffected -- the same discipline as Migration A.

Revision ID: 4d1a6f83c7be
Revises: 9c1e07b4d8fa
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "4d1a6f83c7be"
down_revision = "9c1e07b4d8fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("title_tr", sa.String(300), nullable=False),
        sa.Column("detail_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_campaign_alerts_dedupe_key"),
    )
    op.create_index("ix_campaign_alerts_promotion_id", "campaign_alerts", ["promotion_id"])
    # The read endpoint orders by priority then created_at; the daily mail asks
    # for "the last 24 hours". Both dimensions are indexed separately rather
    # than as one composite, because the priority index is also what the
    # unacknowledged-count query uses on its own.
    op.create_index("ix_campaign_alerts_priority", "campaign_alerts", ["priority"])
    op.create_index("ix_campaign_alerts_created_at", "campaign_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_campaign_alerts_created_at", table_name="campaign_alerts")
    op.drop_index("ix_campaign_alerts_priority", table_name="campaign_alerts")
    op.drop_index("ix_campaign_alerts_promotion_id", table_name="campaign_alerts")
    op.drop_table("campaign_alerts")
