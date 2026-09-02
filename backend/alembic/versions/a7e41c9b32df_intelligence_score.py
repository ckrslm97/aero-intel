"""haber zekâ skoru + promosyon çıkarım işareti

Six additive, nullable columns on `article_enrichment`.

Why a new column instead of rewriting `importance_score`: that column is still
read by the frontend, by app/services/edition_service.py and by every existing
`min_importance` caller. Overwriting it in place would change what all of them
mean in one deploy, with no way to compare old and new rankings against each
other. The two live side by side until the frontend moves over.

  intelligence_score  0-1, the weighted combination of the eight sub-scores in
                      app/services/news_scoring.py. Indexed: it is a sort key
                      and a filter floor for the article list, the same way
                      importance_score is, and an unindexed float on a table
                      this size means a sequential scan per page.
  score_detail        the components AND the weights that produced the score,
                      so a row scored today stays explainable after the weights
                      have moved on. Same pattern as promotions.confidence_detail.
  rm_impact           the model's three impact axes. NULLABLE AND NULL IS
  demand_impact       LOAD-BEARING: only the daily shortlist (~20 articles) is
  capacity_impact     scored by the LLM, so NULL means "not asked" and 0.0
                      means "asked, and the answer is no impact". Defaulting
                      these to 0.0 would erase that distinction and make every
                      unscored article look like one the model had rejected.

  promo_extracted_at  when app/pipeline/promotions.py last ran extraction for
                      this article, campaign or not. The guard against the
                      re-read leak: `_candidate_articles` had no memory, so the
                      :10/:40 cron re-sent every archived campaign article to
                      the LLM 48 times a day. A timestamp rather than a boolean
                      because "when" is what makes a stuck backlog diagnosable,
                      and it records the NOT_APPLICABLE outcome the same way
                      app/pipeline/outcomes.py argues every other classifier
                      should ("persisted so the next run does not spend another
                      call re-asking a question that was already answered").

Nullable throughout, so no backfill: existing rows start NULL and fill in on
the first enrichment/selection run after deploy. A NULL intelligence_score
sorts last under `NULLS LAST` everywhere it is read, so the archive keeps
working unchanged while it fills.

Revision ID: a7e41c9b32df
Revises: b8f3d21c7a45
Create Date: 2026-09-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7e41c9b32df"
down_revision: Union[str, None] = "b8f3d21c7a45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment", sa.Column("intelligence_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "article_enrichment",
        sa.Column("score_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("article_enrichment", sa.Column("rm_impact", sa.Float(), nullable=True))
    op.add_column("article_enrichment", sa.Column("demand_impact", sa.Float(), nullable=True))
    op.add_column("article_enrichment", sa.Column("capacity_impact", sa.Float(), nullable=True))
    op.add_column(
        "article_enrichment",
        sa.Column("promo_extracted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_article_enrichment_intelligence_score",
        "article_enrichment",
        ["intelligence_score"],
    )
    # The promotion extractor's candidate query is "campaign articles never
    # extracted", i.e. a NULL test on a column that will be non-NULL for almost
    # every row within a day of deploy. A partial index over just the NULLs is
    # what keeps that query O(backlog) instead of O(archive) as the archive
    # grows -- which is the whole failure this migration's guard exists to fix.
    op.create_index(
        "ix_article_enrichment_promo_pending",
        "article_enrichment",
        ["article_id"],
        postgresql_where=sa.text("promo_extracted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_article_enrichment_promo_pending", table_name="article_enrichment")
    op.drop_index("ix_article_enrichment_intelligence_score", table_name="article_enrichment")
    op.drop_column("article_enrichment", "promo_extracted_at")
    op.drop_column("article_enrichment", "capacity_impact")
    op.drop_column("article_enrichment", "demand_impact")
    op.drop_column("article_enrichment", "rm_impact")
    op.drop_column("article_enrichment", "score_detail")
    op.drop_column("article_enrichment", "intelligence_score")
