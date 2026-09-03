"""promotions.source_published_at: the reporter's clock, out of ours

`promotions.detected_at` is documented on the model as OUR first sighting, and
three surfaces read it that way: the "Yeni" badge, the 48-hour banner and
`GET /promotions/new-count`. The news extractor
(app/pipeline/promotions.py) nevertheless stamped it with the ARTICLE's
`published_at`, so a campaign first extracted this morning out of a three-week-
old trade report was born three weeks old and could never appear as new -- on
the one day a revenue manager needed to see it.

The extractor now stamps `detected_at` with the run's own clock. This column is
where the article's date goes instead, so nothing is lost: "found at 06:00
today" and "the reporting behind it is three weeks old" are both true, both
worth printing, and were never the same fact.

Nullable with no server default and no backfill, deliberately. NULL means "the
source document stated no date" -- which is the truth for every existing row
(nobody recorded one), for the airline-page scraper (a campaign page carries no
publication time) and for the curated seed. A backfill from `detected_at` would
be exactly the fusion this column exists to undo: it would assert that the
reporter published at the moment we happened to scan.

Additive and nullable so an old worker and the new schema can share the
database while the migration lands, as with every other column change here.

Revision ID: e7b1c94d2a58
Revises: d2a45f81c6e7
Create Date: 2026-09-03
"""
import sqlalchemy as sa
from alembic import op

revision = "e7b1c94d2a58"
down_revision = "d2a45f81c6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "promotions",
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("promotions", "source_published_at")
