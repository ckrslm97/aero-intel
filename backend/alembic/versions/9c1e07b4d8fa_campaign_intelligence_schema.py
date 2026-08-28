"""campaign intelligence schema

Phase 1 of the campaign-intelligence rebuild: give every later phase a column
to write into, while changing nothing that runs today.

Strictly additive and strictly nullable, with no server defaults. Migrations
run inline at the start of the scheduled jobs, so for a few minutes an old
worker and a new schema share the database -- an additive-nullable change is
the only shape that cannot break that worker, and a server default would
additionally rewrite the whole table under a lock for no benefit. NULL in any
of these columns means "never classified", which is exactly what the ~200
legacy rows are; they keep being served by /promotions unchanged.

Deliberately absent: a `status` column. UPCOMING / ACTIVE_BOOKING /
BOOKING_CLOSED_TRAVEL_ACTIVE / EXPIRED is a function of the date columns and
today's date, so it is computed at read time. Stored, it would be stale every
morning until a cron caught up, and this project's cron is measurably 2-3 hours
late.

The three new tables cover what a single overwritten `promotions` row cannot
express: campaign_versions (what changed and when -- an in-place update erases
the one fact a revenue desk most wants), campaign_sources (who else said it,
which feeds corroboration and makes conflict resolution explicable), and
scrape_runs (fetch telemetry -- six of seven target carriers sit behind bot
walls that answer 200 OK, so "no new campaigns" and "we have not read the page
since Tuesday" are otherwise indistinguishable).

Backfill: first_seen_at/last_seen_at get detected_at for existing rows, which
is the only honest value we have for them. Everything else stays NULL.

Revision ID: 9c1e07b4d8fa
Revises: 2b7b2bda29b6
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9c1e07b4d8fa"
down_revision = "2b7b2bda29b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- promotions: classification, route, evidence, lifecycle -------------
    op.add_column("promotions", sa.Column("campaign_type", sa.String(40), nullable=True))
    op.add_column("promotions", sa.Column("business_class", sa.String(30), nullable=True))
    op.add_column("promotions", sa.Column("route_scope", sa.String(12), nullable=True))
    op.add_column("promotions", sa.Column("ond", sa.String(9), nullable=True))
    op.add_column("promotions", sa.Column("origin_code", sa.String(3), nullable=True))
    op.add_column("promotions", sa.Column("dest_code", sa.String(3), nullable=True))
    op.add_column("promotions", sa.Column("route_json", postgresql.JSONB(), nullable=True))
    op.add_column("promotions", sa.Column("attrs_json", postgresql.JSONB(), nullable=True))
    op.add_column("promotions", sa.Column("evidence_json", postgresql.JSONB(), nullable=True))
    op.add_column("promotions", sa.Column("classification_reason", sa.Text(), nullable=True))
    op.add_column("promotions", sa.Column("review_required", sa.Boolean(), nullable=True))
    op.add_column("promotions", sa.Column("conflict_detected", sa.Boolean(), nullable=True))
    op.add_column("promotions", sa.Column("date_flags_json", postgresql.JSONB(), nullable=True))
    op.add_column("promotions", sa.Column("page_published_at", sa.Date(), nullable=True))
    op.add_column("promotions", sa.Column("page_updated_at", sa.Date(), nullable=True))
    op.add_column("promotions", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column(
        "promotions", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "promotions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "promotions", sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("promotions", sa.Column("raw_text", sa.Text(), nullable=True))

    # Only the dimensions the analyst table actually filters or groups on --
    # the JSONB payloads and free text are read per row, never searched.
    op.create_index("ix_promotions_campaign_type", "promotions", ["campaign_type"])
    op.create_index("ix_promotions_business_class", "promotions", ["business_class"])
    op.create_index("ix_promotions_ond", "promotions", ["ond"])
    op.create_index("ix_promotions_review_required", "promotions", ["review_required"])
    op.create_index("ix_promotions_content_hash", "promotions", ["content_hash"])

    # The legacy rows were seen exactly once, when we detected them. Anything
    # else here would be invented.
    op.execute(
        "UPDATE promotions SET first_seen_at = detected_at, last_seen_at = detected_at "
        "WHERE first_seen_at IS NULL"
    )

    # --- campaign_versions --------------------------------------------------
    op.create_table(
        "campaign_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint(
            "promotion_id", "version_no", name="uq_campaign_versions_promotion_no"
        ),
    )
    op.create_index("ix_campaign_versions_promotion_id", "campaign_versions", ["promotion_id"])

    # --- campaign_sources ---------------------------------------------------
    op.create_table(
        "campaign_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("source_name", sa.String(120), nullable=True),
        sa.Column("source_tier", sa.String(20), nullable=True),
        sa.Column("source_quality", sa.Float(), nullable=True),
        sa.Column("page_published_at", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_excerpt", sa.Text(), nullable=True),
        sa.UniqueConstraint("promotion_id", "url", name="uq_campaign_sources_promotion_url"),
    )
    op.create_index("ix_campaign_sources_promotion_id", "campaign_sources", ["promotion_id"])

    # --- scrape_runs --------------------------------------------------------
    op.create_table(
        "scrape_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("carrier_code", sa.String(6), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("changed", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_scrape_runs_carrier_code", "scrape_runs", ["carrier_code"])
    op.create_index("ix_scrape_runs_outcome", "scrape_runs", ["outcome"])
    # "How did <carrier> last do?" -- the only question this table is asked.
    op.create_index("ix_scrape_runs_carrier_started", "scrape_runs", ["carrier_code", "started_at"])


def downgrade() -> None:
    op.drop_table("scrape_runs")
    op.drop_table("campaign_sources")
    op.drop_table("campaign_versions")

    op.drop_index("ix_promotions_content_hash", table_name="promotions")
    op.drop_index("ix_promotions_review_required", table_name="promotions")
    op.drop_index("ix_promotions_ond", table_name="promotions")
    op.drop_index("ix_promotions_business_class", table_name="promotions")
    op.drop_index("ix_promotions_campaign_type", table_name="promotions")

    for column in (
        "raw_text",
        "last_changed_at",
        "last_seen_at",
        "first_seen_at",
        "content_hash",
        "page_updated_at",
        "page_published_at",
        "date_flags_json",
        "conflict_detected",
        "review_required",
        "classification_reason",
        "evidence_json",
        "attrs_json",
        "route_json",
        "dest_code",
        "origin_code",
        "ond",
        "route_scope",
        "business_class",
        "campaign_type",
    ):
        op.drop_column("promotions", column)
