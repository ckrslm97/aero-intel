"""source tier and language

Additive: both columns are nullable, and nothing reads them until
ensure_seeded() writes them on the next reconcile (app/ingest/sources_seed.py
now declares a tier and language per source). `tier` replaces the trust_weight
bucketing app/agents/runner.py used as a stand-in; `language` closes the gap
where a source's own declared language never reached
pipeline/language.resolve()'s `declared` parameter, so every article was
detected fresh from scratch even for a feed whose language was already known.

Revision ID: cb8885f95f71
Revises: a1f4c7e920bb
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb8885f95f71'
down_revision: Union[str, None] = 'a1f4c7e920bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('tier', sa.String(length=20), nullable=True))
    op.add_column('sources', sa.Column('language', sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column('sources', 'language')
    op.drop_column('sources', 'tier')
