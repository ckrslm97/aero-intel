"""drop the orphaned users table

AeroIntel has no authentication. There is no User model, no login endpoint, no
session handling -- `frontend/src/lib/auth.ts` called /auth/login and /auth/me,
neither of which has ever existed, and it was itself imported by nothing. The
Python side removed `passlib`, `bcrypt` and `python-jose` in the previous
migration's release for the same reason.

What remained was this table, created by the initial schema and orphaned ever
since: rows of `hashed_password` in a production database that nothing can
authenticate against, because the libraries that could verify them are gone.
Stale credential storage with no reader is a liability, not an asset.

Deliberately its own migration rather than folded into the schema change beside
it: this is the one destructive step in the set, and it should be possible to
review, revert, or skip it on its own.

The downgrade recreates the table. It cannot recreate the rows -- if a
deployment turns out to have had real ones, restore from a backup instead.

Revision ID: a1f4c7e920bb
Revises: e3624aa07d6a
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1f4c7e920bb"
down_revision = "e3624aa07d6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")


def downgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.VARCHAR(length=320), autoincrement=False, nullable=False),
        sa.Column("hashed_password", sa.VARCHAR(length=200), autoincrement=False, nullable=False),
        sa.Column("role", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
