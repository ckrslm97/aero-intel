"""source editorial config + fetch health

Eight additive, nullable columns on `sources`, in one migration because they
land in the same reconcile pass and splitting them would mean two deploys for
one feature.

Editorial config (written by ensure_seeded from app/ingest/sources_seed.py):
  priority                 very_high|high|normal|low -- how much the desk wants
                           this source, which is a different axis from `tier`
                           (what kind of publisher it is). See the column
                           docstring in app/models/source.py.
  news_categories          comma-separated taxonomy slugs the source actually
                           feeds. Named apart from the existing `category`
                           column on purpose: that one is the institution type.
  crawl_frequency_minutes  intended polling cadence. Informational -- every
                           source still runs on the single `0 */2 * * *`
                           schedule in .github/workflows/jobs-news.yml.

Fetch health (written by app/services/ingestion_service.py each run):
  last_success_at, last_failure_at, last_http_status, consecutive_failures,
  last_article_count.

The health half closes a hole the codebase had already documented and paid
for: FAA and ICAO produced exactly 0 articles from the day they were seeded,
and only a manual production review ever noticed (see app/ingest/
sources_seed.py). Every run logged it; nothing accumulated it. These columns
accumulate it, and data_quality_service.py's two new checks read them.

Nullable throughout, so existing rows need no backfill -- they start null and
fill in on the first ingestion run after deploy. `consecutive_failures` gets a
server_default of 0 so rows created outside the seeder still count from zero
rather than from null.

Revision ID: b8f3d21c7a45
Revises: c1b93e07af52
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f3d21c7a45'
down_revision: Union[str, None] = 'c1b93e07af52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Editorial configuration.
    op.add_column('sources', sa.Column('priority', sa.String(length=10), nullable=True))
    op.add_column('sources', sa.Column('news_categories', sa.String(length=200), nullable=True))
    op.add_column('sources', sa.Column('crawl_frequency_minutes', sa.Integer(), nullable=True))

    # Fetch health.
    op.add_column(
        'sources', sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'sources', sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('sources', sa.Column('last_http_status', sa.Integer(), nullable=True))
    op.add_column(
        'sources',
        sa.Column('consecutive_failures', sa.Integer(), nullable=True, server_default='0'),
    )
    op.add_column('sources', sa.Column('last_article_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('sources', 'last_article_count')
    op.drop_column('sources', 'consecutive_failures')
    op.drop_column('sources', 'last_http_status')
    op.drop_column('sources', 'last_failure_at')
    op.drop_column('sources', 'last_success_at')
    op.drop_column('sources', 'crawl_frequency_minutes')
    op.drop_column('sources', 'news_categories')
    op.drop_column('sources', 'priority')
