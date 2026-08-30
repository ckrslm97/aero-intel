"""article_enrichment: store the "Neden önemli?" assessment

The Gazete's drawer explains what the pipeline decided about a story --
category, confidence, corroboration -- but never what the story means for the
desk reading it. That sentence is the one thing a revenue analyst was writing
in the margin by hand.

Nullable, and NULL is the normal case rather than a backlog: the sentence costs
a live model call on top of translation, so app/pipeline/enrich.py generates it
only for articles whose focus-weighted importance clears its threshold and only
when a translation-capable provider is configured. A handful of rows a day
carry one; every other row renders without the block, exactly as before.

Text rather than String(n) for the same reason aviation_impact_note is: this is
a model-written sentence, and a column-level cap would truncate it mid-word
instead of rejecting it. The provider caps its own answer.

Revision ID: a7e2c31b60d4
Revises: c9f4b217ae30
Create Date: 2026-08-30 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7e2c31b60d4"
down_revision: Union[str, None] = "c9f4b217ae30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment", sa.Column("why_important_tr", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("article_enrichment", "why_important_tr")
