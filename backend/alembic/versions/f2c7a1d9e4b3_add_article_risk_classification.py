"""add article risk classification fields

Re-parented onto the promotions migration when feat/risk-radari merged main:
both were originally cut from b4357df7d0de, which left the tree with two
alembic heads and made `alembic upgrade head` fail outright. The two touch
different tables (article_enrichment vs promotions), so ordering them linearly
is equivalent to the branch point and needs no merge revision.

Revision ID: f2c7a1d9e4b3
Revises: f2c81a4b90de
Create Date: 2026-08-23 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c7a1d9e4b3'
down_revision: Union[str, None] = 'f2c81a4b90de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All nullable: most articles are not risk events, so null is the normal
    # value here rather than a missing one. Existing rows simply carry no
    # classification until `python -m app.cli backfill-risks` (or the next
    # enrichment pass) fills them in -- see app/pipeline/enrich.py.
    op.add_column('article_enrichment', sa.Column('risk_type', sa.String(length=20), nullable=True))
    op.add_column('article_enrichment', sa.Column('risk_family', sa.String(length=20), nullable=True))
    op.add_column('article_enrichment', sa.Column('risk_severity', sa.String(length=10), nullable=True))
    op.add_column('article_enrichment', sa.Column('risk_country', sa.String(length=80), nullable=True))
    op.add_column('article_enrichment', sa.Column('risk_city', sa.String(length=80), nullable=True))
    # Indexed on the three columns /risks filters and groups by. risk_severity
    # and risk_city are not indexed: severity has three values (no selectivity)
    # and city is only ever read back on rows already narrowed by country.
    op.create_index(
        op.f('ix_article_enrichment_risk_type'), 'article_enrichment', ['risk_type'], unique=False
    )
    op.create_index(
        op.f('ix_article_enrichment_risk_family'), 'article_enrichment', ['risk_family'], unique=False
    )
    op.create_index(
        op.f('ix_article_enrichment_risk_country'), 'article_enrichment', ['risk_country'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_article_enrichment_risk_country'), table_name='article_enrichment')
    op.drop_index(op.f('ix_article_enrichment_risk_family'), table_name='article_enrichment')
    op.drop_index(op.f('ix_article_enrichment_risk_type'), table_name='article_enrichment')
    op.drop_column('article_enrichment', 'risk_city')
    op.drop_column('article_enrichment', 'risk_country')
    op.drop_column('article_enrichment', 'risk_severity')
    op.drop_column('article_enrichment', 'risk_family')
    op.drop_column('article_enrichment', 'risk_type')
