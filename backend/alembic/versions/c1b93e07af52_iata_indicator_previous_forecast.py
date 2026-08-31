"""iata_indicators: carry the previous edition's figure for the same period

IATA publishes its Global Outlook roughly twice a year and revises the same
forecast between editions -- the June 2026 report halves its own 2026
net-profit number, $41bn down to $23bn, against December 2025. A row that
stores only the current figure renders the conclusion and drops the news.

Three nullable columns rather than a second `iata_indicators` row with an older
publication_date: the natural key is (metric, kind, period_end, region), so a
revision IS the same claim restated, and modelling it as a second row would
make every "which number is current?" read a sort. NULL is the ordinary state
-- actuals have no earlier forecast of themselves, and a forecast whose prior
edition nobody verified must stay empty rather than carry a guess.

previous_source_url is String(600) to match `source_url` on the same table.

Revision ID: c1b93e07af52
Revises: a7e2c31b60d4
Create Date: 2026-08-31 10:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1b93e07af52"
down_revision: Union[str, None] = "a7e2c31b60d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("iata_indicators", sa.Column("previous_value", sa.Float(), nullable=True))
    op.add_column(
        "iata_indicators", sa.Column("previous_publication_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "iata_indicators", sa.Column("previous_source_url", sa.String(length=600), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("iata_indicators", "previous_source_url")
    op.drop_column("iata_indicators", "previous_publication_date")
    op.drop_column("iata_indicators", "previous_value")
