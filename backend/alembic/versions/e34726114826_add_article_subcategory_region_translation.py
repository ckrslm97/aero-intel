"""add article subcategory, region, and translation fields

Revision ID: e34726114826
Revises: 07904696aa02
Create Date: 2026-07-14 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e34726114826'
down_revision: Union[str, None] = '07904696aa02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All nullable -- existing rows simply have no subcategory/region/translation
    # until the next enrichment pass re-populates them (see app/pipeline/enrich.py).
    op.add_column('article_enrichment', sa.Column('subcategory', sa.String(length=50), nullable=True))
    op.add_column('article_enrichment', sa.Column('region', sa.String(length=50), nullable=True))
    op.add_column('article_enrichment', sa.Column('headline_tr', sa.Text(), nullable=True))
    op.add_column('article_enrichment', sa.Column('summary_tr', sa.Text(), nullable=True))
    op.add_column('article_enrichment', sa.Column('translated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('article_enrichment', sa.Column('translation_provider', sa.String(length=30), nullable=True))
    op.create_index(
        op.f('ix_article_enrichment_subcategory'), 'article_enrichment', ['subcategory'], unique=False
    )
    op.create_index(
        op.f('ix_article_enrichment_region'), 'article_enrichment', ['region'], unique=False
    )

    # The old flat taxonomy used "routes" where the new one uses "network".
    op.execute("UPDATE article_enrichment SET category = 'network' WHERE category = 'routes'")


def downgrade() -> None:
    op.execute("UPDATE article_enrichment SET category = 'routes' WHERE category = 'network'")
    op.drop_index(op.f('ix_article_enrichment_region'), table_name='article_enrichment')
    op.drop_index(op.f('ix_article_enrichment_subcategory'), table_name='article_enrichment')
    op.drop_column('article_enrichment', 'translation_provider')
    op.drop_column('article_enrichment', 'translated_at')
    op.drop_column('article_enrichment', 'summary_tr')
    op.drop_column('article_enrichment', 'headline_tr')
    op.drop_column('article_enrichment', 'region')
    op.drop_column('article_enrichment', 'subcategory')
