"""risk verification: currency flags, aviation relevance and location roles

Eleven nullable columns on `article_enrichment`, in one migration because they
are one change: the Risk Radarı's three verification gates, and each gate needs
its own evidence column to be auditable rather than merely applied.

**Currency (5 columns).** `is_current_event`, `is_historical`, `is_analysis`,
`is_opinion`, `is_recap`. NULL is "nobody looked" and is emphatically NOT
False, on every one of them. The gate in app/api/v1/risks.py is therefore
`is_current_event IS NOT FALSE` -- an unscored row publishes -- because LLM
coverage of this feed is partial and `IS TRUE` would delete the archive rather
than filter it.

`is_developing` and `is_resolved` from the same section of the spec are
deliberately NOT here. There is no lifecycle signal anywhere in this pipeline:
the feed carries publication times and never event times, so nothing can say an
event is ongoing or over. Columns for them would be columns nothing could ever
fill honestly.

**Aviation relevance (4 columns).** `aviation_relevance_score` 0-1, plus the
sentence it was read off (`aviation_impact_evidence`), whether that sentence
reports or forecasts (`aviation_impact_status`), and which pass produced the
score at all (`aviation_relevance_source`: llm | heuristic | unscored).

The last one is what makes the gate tightenable. A score of NULL and a score of
0.1 are different facts, and a gate that cannot tell them apart is a gate that
deletes rows nobody measured -- so the denominator has to be stored, not
inferred later from which provider happened to be configured that week.

**Location (2 columns).** `mentioned_locations` (JSONB: every place the article
named, each with the role it played -- event or source) and
`location_confidence` (0-1). `risk_country`/`risk_city` keep their meaning:
where the EVENT happened.

The bug they exist for: the resolver took the first country entity in the text,
so "Washington said an earthquake struck Japan" pinned the earthquake to the
United States. The rejected mention is now kept with role="source" instead of
being silently discarded, which is what makes the rejection reviewable.

No coordinate/polygon column and no coordinate-vs-country check: placement is a
centroid table in the frontend, there is no polygon dataset on the server, and
a check needs something to check against. `location_confidence` is the honest
substitute -- the map refuses to pin below the threshold rather than drawing a
confident dot on a guess.

Additive, nullable, no server defaults: migrations run inline at the start of
the scheduled jobs, so an old worker and a new schema share the database for a
few minutes, and this is the only shape that cannot break that worker. Nothing
is backfilled -- every existing row keeps NULL on all eleven, which every gate
reads as "unscored, publish it".

Revision ID: d2a45f81c6e7
Revises: c4f18a2b7d31
Create Date: 2026-09-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d2a45f81c6e7"
down_revision = "c4f18a2b7d31"
branch_labels = None
depends_on = None

_TABLE = "article_enrichment"

_BOOLEAN_FLAGS = (
    "is_current_event",
    "is_historical",
    "is_analysis",
    "is_opinion",
    "is_recap",
)


def upgrade() -> None:
    for name in _BOOLEAN_FLAGS:
        op.add_column(_TABLE, sa.Column(name, sa.Boolean(), nullable=True))

    op.add_column(_TABLE, sa.Column("aviation_relevance_score", sa.Float(), nullable=True))
    op.add_column(
        _TABLE, sa.Column("aviation_relevance_source", sa.String(length=12), nullable=True)
    )
    op.add_column(_TABLE, sa.Column("aviation_impact_evidence", sa.Text(), nullable=True))
    op.add_column(
        _TABLE, sa.Column("aviation_impact_status", sa.String(length=10), nullable=True)
    )

    op.add_column(
        _TABLE,
        sa.Column("mentioned_locations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(_TABLE, sa.Column("location_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "location_confidence")
    op.drop_column(_TABLE, "mentioned_locations")
    op.drop_column(_TABLE, "aviation_impact_status")
    op.drop_column(_TABLE, "aviation_impact_evidence")
    op.drop_column(_TABLE, "aviation_relevance_source")
    op.drop_column(_TABLE, "aviation_relevance_score")
    for name in reversed(_BOOLEAN_FLAGS):
        op.drop_column(_TABLE, name)
