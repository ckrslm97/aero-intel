"""index news_events.primary_article_id

Faz 14 (performance): Hub/Biz's per-airport and per-carrier event lookups
(hub_service.py, biz_service.py, network_signals_service.py) all filter or
join on this column -- added once those callers existed.

Revision ID: 2b7b2bda29b6
Revises: ee67ea48678c
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2b7b2bda29b6'
down_revision: Union[str, None] = 'ee67ea48678c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_news_events_primary_article_id', 'news_events', ['primary_article_id']
    )


def downgrade() -> None:
    op.drop_index('ix_news_events_primary_article_id', table_name='news_events')
