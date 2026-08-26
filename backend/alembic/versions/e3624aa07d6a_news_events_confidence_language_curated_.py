"""news events, confidence, language, curated forecasts

The v2 schema. Additive only: every column added here is nullable and every
table is new, so the running v1 code neither sees nor is broken by any of it.
That is what lets this deploy ahead of the pipeline that fills it.

What is here and why:

* `news_events` -- the Gazete's unit becomes the event, not the article. The
  same story from three feeds was classified three times and could land in
  three categories; it is now classified once, on the cluster's primary source.
  Risk moves here too, because an earthquake is one event however many outlets
  covered it, and the country rollup was counting reports.
* `articles.language` -- there was no language detection anywhere, which is how
  18% of the feed reached a Turkish UI as untranslated German and Spanish.
* `articles.rejection_reason` -- a rejected article becomes a fact with a reason
  rather than an absence.
* confidence columns on events and promotions -- the band is what read
  endpoints filter on; `low` rows stay in the table as the record of what the
  pipeline chose not to show.
* `promotions.validation_state` and `superseded_at` -- 55% of what that table
  published was not a campaign, and 92% had no sale date. Rows now have to earn
  the page, and the bad ones are marked rather than destroyed.
* `fx_forecasts` / `iata_indicators` -- human-curated reference data. See
  app/models/curated.py for why neither can honestly be scraped.

Revision ID: e3624aa07d6a
Revises: f2c7a1d9e4b3
Create Date: 2026-08-26 10:01:14.899281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e3624aa07d6a'
down_revision: Union[str, None] = 'f2c7a1d9e4b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fx_forecasts',
    sa.Column('institution', sa.String(length=120), nullable=False),
    sa.Column('currency_pair', sa.String(length=16), nullable=False),
    sa.Column('horizon_label', sa.String(length=40), nullable=False),
    sa.Column('horizon_months', sa.Integer(), nullable=True),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('publication_date', sa.Date(), nullable=False),
    sa.Column('source_url', sa.String(length=600), nullable=False),
    sa.Column('entered_by', sa.String(length=120), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note_tr', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fx_forecasts_currency_pair'), 'fx_forecasts', ['currency_pair'], unique=False)
    op.create_index('ix_fx_forecasts_pair_published', 'fx_forecasts', ['currency_pair', 'publication_date'], unique=False)
    op.create_index(op.f('ix_fx_forecasts_publication_date'), 'fx_forecasts', ['publication_date'], unique=False)
    op.create_table('iata_indicators',
    sa.Column('metric', sa.String(length=60), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('period_label_tr', sa.String(length=60), nullable=False),
    sa.Column('region', sa.String(length=30), nullable=True),
    sa.Column('publication_date', sa.Date(), nullable=False),
    sa.Column('source_url', sa.String(length=600), nullable=False),
    sa.Column('interpretation_tr', sa.Text(), nullable=True),
    sa.Column('entered_by', sa.String(length=120), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_iata_indicators_kind'), 'iata_indicators', ['kind'], unique=False)
    op.create_index('ix_iata_indicators_kind_period', 'iata_indicators', ['kind', 'period_end'], unique=False)
    op.create_index(op.f('ix_iata_indicators_metric'), 'iata_indicators', ['metric'], unique=False)
    op.create_index('ix_iata_indicators_metric_published', 'iata_indicators', ['metric', 'publication_date'], unique=False)
    op.create_index(op.f('ix_iata_indicators_publication_date'), 'iata_indicators', ['publication_date'], unique=False)
    op.create_index(op.f('ix_iata_indicators_region'), 'iata_indicators', ['region'], unique=False)
    op.create_table('news_events',
    sa.Column('slug', sa.String(length=220), nullable=False),
    sa.Column('title_tr', sa.String(length=500), nullable=True),
    sa.Column('summary_tr', sa.Text(), nullable=True),
    sa.Column('primary_article_id', sa.UUID(), nullable=True),
    sa.Column('category', sa.String(length=50), nullable=True),
    sa.Column('subcategory', sa.String(length=50), nullable=True),
    sa.Column('region', sa.String(length=30), nullable=True),
    sa.Column('risk_type', sa.String(length=30), nullable=True),
    sa.Column('risk_family', sa.String(length=30), nullable=True),
    sa.Column('risk_severity', sa.String(length=10), nullable=True),
    sa.Column('risk_country', sa.String(length=80), nullable=True),
    sa.Column('risk_city', sa.String(length=80), nullable=True),
    sa.Column('risk_score', sa.Float(), nullable=True),
    sa.Column('risk_assessed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confidence_score', sa.Float(), nullable=True),
    sa.Column('confidence_band', sa.String(length=10), nullable=True),
    sa.Column('confidence_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('not_applicable_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('article_count', sa.Integer(), nullable=False),
    sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(
        ['primary_article_id'], ['articles.id'],
        name='fk_news_events_primary_article_id', ondelete='SET NULL',
    ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index('ix_news_events_band_last_seen', 'news_events', ['confidence_band', 'last_seen'], unique=False)
    op.create_index(op.f('ix_news_events_category'), 'news_events', ['category'], unique=False)
    op.create_index('ix_news_events_category_last_seen', 'news_events', ['category', 'last_seen'], unique=False)
    op.create_index(op.f('ix_news_events_confidence_band'), 'news_events', ['confidence_band'], unique=False)
    op.create_index(op.f('ix_news_events_first_seen'), 'news_events', ['first_seen'], unique=False)
    op.create_index(op.f('ix_news_events_is_published'), 'news_events', ['is_published'], unique=False)
    op.create_index(op.f('ix_news_events_last_seen'), 'news_events', ['last_seen'], unique=False)
    op.create_index(op.f('ix_news_events_region'), 'news_events', ['region'], unique=False)
    op.create_index(op.f('ix_news_events_risk_country'), 'news_events', ['risk_country'], unique=False)
    op.create_index('ix_news_events_risk_family_last_seen', 'news_events', ['risk_family', 'last_seen'], unique=False)
    op.create_index(op.f('ix_news_events_risk_type'), 'news_events', ['risk_type'], unique=False)
    op.add_column('articles', sa.Column('language', sa.String(length=5), nullable=True))
    op.add_column('articles', sa.Column('event_id', sa.UUID(), nullable=True))
    op.add_column('articles', sa.Column('rejection_reason', sa.String(length=60), nullable=True))
    op.create_index(op.f('ix_articles_language'), 'articles', ['language'], unique=False)
    op.create_index('ix_articles_status_fetched_at', 'articles', ['status', 'fetched_at'], unique=False)
    op.create_foreign_key(
        'fk_articles_event_id', 'articles', 'news_events', ['event_id'], ['id'],
        ondelete='SET NULL',
    )
    op.add_column('promotions', sa.Column('markets_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('promotions', sa.Column('event_id', sa.UUID(), nullable=True))
    op.add_column('promotions', sa.Column('validation_state', sa.String(length=20), nullable=True))
    op.add_column('promotions', sa.Column('confidence_score', sa.Float(), nullable=True))
    op.add_column('promotions', sa.Column('confidence_band', sa.String(length=10), nullable=True))
    op.add_column('promotions', sa.Column('confidence_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('promotions', sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_promotions_confidence_band'), 'promotions', ['confidence_band'], unique=False)
    op.create_foreign_key(
        'fk_promotions_event_id', 'promotions', 'news_events', ['event_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_promotions_event_id', 'promotions', type_='foreignkey')
    op.drop_index(op.f('ix_promotions_confidence_band'), table_name='promotions')
    op.drop_column('promotions', 'superseded_at')
    op.drop_column('promotions', 'confidence_detail')
    op.drop_column('promotions', 'confidence_band')
    op.drop_column('promotions', 'confidence_score')
    op.drop_column('promotions', 'validation_state')
    op.drop_column('promotions', 'event_id')
    op.drop_column('promotions', 'markets_json')
    op.drop_constraint('fk_articles_event_id', 'articles', type_='foreignkey')
    op.drop_index('ix_articles_status_fetched_at', table_name='articles')
    op.drop_index(op.f('ix_articles_language'), table_name='articles')
    op.drop_column('articles', 'rejection_reason')
    op.drop_column('articles', 'event_id')
    op.drop_column('articles', 'language')
    op.drop_index(op.f('ix_news_events_risk_type'), table_name='news_events')
    op.drop_index('ix_news_events_risk_family_last_seen', table_name='news_events')
    op.drop_index(op.f('ix_news_events_risk_country'), table_name='news_events')
    op.drop_index(op.f('ix_news_events_region'), table_name='news_events')
    op.drop_index(op.f('ix_news_events_last_seen'), table_name='news_events')
    op.drop_index(op.f('ix_news_events_is_published'), table_name='news_events')
    op.drop_index(op.f('ix_news_events_first_seen'), table_name='news_events')
    op.drop_index(op.f('ix_news_events_confidence_band'), table_name='news_events')
    op.drop_index('ix_news_events_category_last_seen', table_name='news_events')
    op.drop_index(op.f('ix_news_events_category'), table_name='news_events')
    op.drop_index('ix_news_events_band_last_seen', table_name='news_events')
    op.drop_table('news_events')
    op.drop_index(op.f('ix_iata_indicators_region'), table_name='iata_indicators')
    op.drop_index(op.f('ix_iata_indicators_publication_date'), table_name='iata_indicators')
    op.drop_index('ix_iata_indicators_metric_published', table_name='iata_indicators')
    op.drop_index(op.f('ix_iata_indicators_metric'), table_name='iata_indicators')
    op.drop_index('ix_iata_indicators_kind_period', table_name='iata_indicators')
    op.drop_index(op.f('ix_iata_indicators_kind'), table_name='iata_indicators')
    op.drop_table('iata_indicators')
    op.drop_index(op.f('ix_fx_forecasts_publication_date'), table_name='fx_forecasts')
    op.drop_index('ix_fx_forecasts_pair_published', table_name='fx_forecasts')
    op.drop_index(op.f('ix_fx_forecasts_currency_pair'), table_name='fx_forecasts')
    op.drop_table('fx_forecasts')
