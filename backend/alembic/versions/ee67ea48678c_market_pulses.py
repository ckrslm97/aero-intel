"""market pulses

New table only. The daily Kokpit summary generated over already-curated
numbers (see app/services/market_pulse_service.py) -- nothing existing reads
or writes to it yet.

Revision ID: ee67ea48678c
Revises: cb8885f95f71
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ee67ea48678c'
down_revision: Union[str, None] = 'cb8885f95f71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'market_pulses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('summary_tr', sa.Text(), nullable=False),
        sa.Column('citations', postgresql.JSONB(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_market_pulses_generated_at', 'market_pulses', ['generated_at']
    )


def downgrade() -> None:
    op.drop_index('ix_market_pulses_generated_at', table_name='market_pulses')
    op.drop_table('market_pulses')
