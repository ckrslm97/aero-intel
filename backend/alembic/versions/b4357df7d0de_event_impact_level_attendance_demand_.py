"""event impact level, attendance, demand effect

Revision ID: b4357df7d0de
Revises: d5a81c3f76e4
Create Date: 2026-07-22 18:52:47.993593

Hand-trimmed. --autogenerate also proposed dropping ix_entities_type_code,
ix_kpis_metric_primary_asof and four article indexes: those were created by an
earlier raw-SQL migration for measured hot paths and are invisible to the model
metadata, so autogenerate reads them as stale. They are not. It also proposed
dropping the now-unused `users` table -- true, but deleting data is not this
migration's job.

The two NOT NULL columns carry a server_default: aviation_events already has
rows in production, and adding a NOT NULL column without one fails outright.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4357df7d0de'
down_revision: Union[str, None] = 'd5a81c3f76e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'aviation_events',
        sa.Column('impact_level', sa.String(length=10), nullable=False, server_default='medium'),
    )
    op.add_column('aviation_events', sa.Column('attendance', sa.Integer(), nullable=True))
    op.add_column(
        'aviation_events',
        sa.Column('demand_effect_tr', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index(
        op.f('ix_aviation_events_impact_level'), 'aviation_events', ['impact_level'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_aviation_events_impact_level'), table_name='aviation_events')
    op.drop_column('aviation_events', 'demand_effect_tr')
    op.drop_column('aviation_events', 'attendance')
    op.drop_column('aviation_events', 'impact_level')
