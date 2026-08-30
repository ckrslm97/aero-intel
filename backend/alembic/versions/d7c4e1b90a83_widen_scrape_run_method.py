"""widen scrape_runs.method

`scrape_runs.method` was sized String(10) when the column only ever held
`static` or `browser`. Round 9 added two more fetch methods and one of them --
`impersonate`, the curl_cffi TLS-fingerprint path that finally gets a 200 out of
turkishairlines.com -- is eleven characters. The first scheduled Azure run of
the deep scan therefore proved the fetch works and then died on the INSERT that
was recording it (StringDataRightTruncationError), taking the whole sweep with
it before anything was committed.

Widening rather than renaming the value: `impersonate` is the truthful name of
what the fetcher does, and shortening it to fit a column would leave the log
lying about the experiment this table exists to run.

Additive and non-destructive: a VARCHAR widening is a catalogue-only change in
Postgres (no table rewrite, no lock beyond the brief ACCESS EXCLUSIVE), every
existing value still fits, and an old worker running against the new schema
mid-deploy writes exactly what it wrote before.

Revision ID: d7c4e1b90a83
Revises: 4d1a6f83c7be
Create Date: 2026-08-30
"""
import sqlalchemy as sa
from alembic import op

revision = "d7c4e1b90a83"
down_revision = "4d1a6f83c7be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "scrape_runs",
        "method",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing back would truncate any `impersonate` row written since the
    # upgrade, so the values are shortened to fit first. Losing the distinction
    # between the two browserless methods is the honest cost of going back to a
    # column that cannot hold their names.
    op.execute(
        "UPDATE scrape_runs SET method = left(method, 10) WHERE length(method) > 10"
    )
    op.alter_column(
        "scrape_runs",
        "method",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
