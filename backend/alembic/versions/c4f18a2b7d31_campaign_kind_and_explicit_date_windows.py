"""campaign kind and the explicitly-stated date windows

Two additions the campaign surface asked for, in one migration because they
land on one table and a second lock on `promotions` buys nothing.

**Four date columns.** Airline copy sometimes states three windows where the
schema had room for two: a campaign period, a ticketing deadline and a travel
window, on top of (or instead of) the sale window. `ticketing_start/end` and
`campaign_start/end` hold the first two *only when the source states them
separately and explicitly*; a page that gives one window is giving the sale
window and these four stay NULL. Nothing is copied into them and nothing is
inferred, so NULL keeps meaning "the source did not say", never "same as the
sale window".

Note what is NOT renamed: `sale_starts`/`sale_ends` stay the sale/reservation
window. Three writer paths, `services/campaign_status.py`, the timeline and the
analyst export all read those names, and a rename would be a schema-wide
rewrite in exchange for a better word.

**campaign_kind.** CAMPAIGN (the offer is a price: FLASH_SALE, PERCENT_DISCOUNT,
BLACK_FRIDAY ...) or PROMOTION (the offer is a mechanism, a channel or an
audience: STUDENT_PROMOTION, LOYALTY_PROMOTION, ANCILLARY_PROMOTION ...). The
alternative on the table was splitting `promotions` into two tables, which
would have rewritten every read path, every foreign key from campaign_versions
/ campaign_sources / campaign_alerts, and the frontend, to express what one
derived column expresses.

At runtime the kind is derived from `campaign_type` through
taxonomy.CAMPAIGN_TYPE_TO_KIND, which is the single source every write path
reads. The backfill below is a **frozen snapshot** of that table rather than an
import of it, because a migration is history: importing live application code
would make this revision produce a different database next year than it
produced today, which is the one thing a migration must never do. No other
migration in this repo imports from `app` either.

The two are kept in step by `python -m app.cli backfill-campaign-kind`, which
re-derives every row from the live taxonomy and is idempotent -- so a campaign
type added after this revision is filled in by running that, never by editing
this file. Rows typed OTHER, and every unclassified legacy row, keep
campaign_kind NULL: "we could not name this offer" is not evidence for either
bucket.

Additive, nullable, no server defaults: migrations run inline at the start of
the scheduled jobs, so an old worker and a new schema share the database for a
few minutes, and this is the only shape that cannot break that worker.

Revision ID: c4f18a2b7d31
Revises: a7e41c9b32df
Create Date: 2026-09-03
"""
import sqlalchemy as sa
from alembic import op

revision = "c4f18a2b7d31"
down_revision = "a7e41c9b32df"
branch_labels = None
depends_on = None

#: Snapshot of taxonomy.CAMPAIGN_TYPE_TO_KIND as of this revision. See the
#: docstring: history is frozen on purpose, and later mapping changes are
#: applied by the CLI backfill rather than by rewriting this list.
_CAMPAIGN_TYPES: dict[str, tuple[str, ...]] = {
    "CAMPAIGN": (
        "FARE_DISCOUNT",
        "PERCENT_DISCOUNT",
        "FIXED_FARE",
        "FLASH_SALE",
        "EARLY_BOOKING",
        "LAST_MINUTE",
        "ROUND_TRIP_PROMOTION",
        "ONE_WAY_PROMOTION",
        "SEASONAL_PROMOTION",
        "BLACK_FRIDAY",
        "CYBER_MONDAY",
        "SUMMER_SALE",
        "WINTER_SALE",
        "RAMADAN_PROMOTION",
        "EID_PROMOTION",
        "NATIONAL_HOLIDAY",
    ),
    "PROMOTION": (
        "STUDENT_PROMOTION",
        "FAMILY_PROMOTION",
        "CORPORATE_PROMOTION",
        "PARTNER_PROMOTION",
        "LOYALTY_PROMOTION",
        "MILES_PROMOTION",
        "ANCILLARY_PROMOTION",
        "BAGGAGE_PROMOTION",
        "DESTINATION_PROMOTION",
        "NEW_ROUTE_PROMOTION",
    ),
}


def upgrade() -> None:
    for column in ("ticketing_start", "ticketing_end", "campaign_start", "campaign_end"):
        op.add_column("promotions", sa.Column(column, sa.Date(), nullable=True))

    op.add_column("promotions", sa.Column("campaign_kind", sa.String(12), nullable=True))
    op.create_index("ix_promotions_campaign_kind", "promotions", ["campaign_kind"])

    # One UPDATE per kind rather than 27 per type: the table is a few hundred
    # rows, and two statements are two statements to read in the log.
    for kind, types in sorted(_CAMPAIGN_TYPES.items()):
        op.execute(
            sa.text(
                "UPDATE promotions SET campaign_kind = :kind "
                "WHERE campaign_kind IS NULL AND campaign_type IN :types"
            ).bindparams(
                sa.bindparam("kind", value=kind),
                sa.bindparam("types", value=tuple(types), expanding=True),
            )
        )


def downgrade() -> None:
    op.drop_index("ix_promotions_campaign_kind", table_name="promotions")
    for column in (
        "campaign_kind",
        "campaign_end",
        "campaign_start",
        "ticketing_end",
        "ticketing_start",
    ):
        op.drop_column("promotions", column)
