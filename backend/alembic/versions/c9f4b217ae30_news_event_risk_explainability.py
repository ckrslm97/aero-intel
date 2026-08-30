"""news_events: keep the risk score's components and the aviation-impact note

Both values already existed at classification time and were discarded before
the row was written: `pipeline/risk_scoring.score()` returns a
RiskScoreResult whose `.components` the runner read `.score` off and dropped,
and `llm/classify.py`'s RiskAssessment carries an `aviation_impact_note` that
was parsed on every risk call and persisted nowhere.

Additive and nullable, on purpose: every existing row keeps its risk_score and
simply has no breakdown behind it until the next enrichment pass writes one.
Nothing reads these columns as required.

Revision ID: c9f4b217ae30
Revises: d7c4e1b90a83
Create Date: 2026-08-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c9f4b217ae30"
down_revision: Union[str, None] = "d7c4e1b90a83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSONB rather than JSON, matching confidence_detail on the same table:
    # this is a five-key breakdown that a later query may want to reach into
    # ("which component is dragging every score down this week"), and JSON
    # would make that a parse per row.
    op.add_column(
        "news_events",
        sa.Column("risk_score_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Text, not String(n): this is a model-written sentence and a length cap
    # would truncate the explanation rather than reject it.
    op.add_column("news_events", sa.Column("aviation_impact_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("news_events", "aviation_impact_note")
    op.drop_column("news_events", "risk_score_detail")
