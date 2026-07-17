"""store edition pdfs in postgres instead of on disk

Revision ID: adfccfca7f27
Revises: e34726114826
Create Date: 2026-07-16 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'adfccfca7f27'
down_revision: Union[str, None] = 'e34726114826'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'edition_pdfs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('edition_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['edition_id'], ['editions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('edition_id'),
    )
    op.add_column(
        'editions', sa.Column('pdf_generated_at', sa.DateTime(timezone=True), nullable=True)
    )
    # pdf_path pointed at files on one machine's local disk. Nothing to migrate:
    # the bytes were never in the database, and the serverless API can't read
    # that disk -- the next scheduled render repopulates edition_pdfs.
    op.drop_column('editions', 'pdf_path')


def downgrade() -> None:
    op.add_column('editions', sa.Column('pdf_path', sa.String(length=500), nullable=True))
    op.drop_column('editions', 'pdf_generated_at')
    op.drop_table('edition_pdfs')
