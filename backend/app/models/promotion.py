"""Airline campaigns/promotions as first-class rows.

Why its own table rather than a sixth `aviation_events.event_type`: a campaign
is not an event. `aviation_events` has no airline column at all -- it is keyed
on city/country, because a trade show happens *somewhere*, while a campaign is
run *by someone*. The calendar's five event types are also a closed set mapped
one-to-one onto the five --chart-* dataviz tokens; a sixth type would have no
colour left to wear. So campaigns get their own table and their own visual
layer (carrier brand hex, overlay ribbons), and the calendar renders both.

Every date column is nullable on purpose. Campaigns reach us two ways -- an
official campaign page (dated, precise) and press coverage (vague: "this
summer", "through the end of the month", or no window at all). Forcing a date
would mean inventing one, and an invented sale window is indistinguishable
from a measured one once it is drawn as a bar. The frontend renders each
missing field honestly instead: an open-ended bar fades out, a campaign with
no start date at all becomes a point marker at `detected_at` rather than a bar.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Promotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "promotions"

    # IATA code matching entities.code and frontend nav.ts airlineTabs -- this
    # is what binds a row to its brand colour and logo on the timeline.
    airline_code: Mapped[str] = mapped_column(String(6), index=True)
    airline_name: Mapped[str] = mapped_column(String(120))

    title_tr: Mapped[str] = mapped_column(String(300))
    summary_tr: Mapped[str] = mapped_column(Text, default="")

    # "%40'a varan" -> 40. None when the source states no rate (a "9 Euro'dan
    # başlayan" fare campaign has no percentage), and the drawer says so rather
    # than rendering an empty badge.
    discount_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Comma-separated world-region slugs (app/taxonomy.py COUNTRY_TO_REGION
    # values) and/or plain city names, mixed. Deliberately not JSON: the only
    # consumers split on comma and render chips, and a JSON column would buy
    # nothing but a migration's worth of ceremony.
    markets: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: The structured form, for the cascading Region -> Country -> City filter:
    #: {"regions": [...], "countries": [...], "cities": [...]}. The comment above
    #: is right that JSON bought nothing while the only consumer split on commas
    #: and rendered chips -- a cascading filter is the consumer that changes
    #: that. Added alongside rather than replacing `markets`, so the old writer
    #: keeps working until the campaign agent replaces it.
    markets_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # When tickets can be BOUGHT. This is the window the timeline draws and the
    # calendar ribbons, because it is the one a revenue desk has to react to.
    sale_starts: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    sale_ends: Mapped[date | None] = mapped_column(Date, nullable=True)
    # When the discounted ticket can be FLOWN -- usually much later and much
    # wider than the sale window, and what tells you which season is at risk.
    travel_starts: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_ends: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- the two windows a page states separately, when it states them -------
    #
    # Airline copy sometimes distinguishes three things where the two columns
    # above only have room for two:
    #
    #   "Kampanya 1-15 Eylül tarihleri arasındadır. Biletlemenin 20 Eylül'e
    #    kadar tamamlanması gerekmektedir. 1 Ekim - 31 Aralık arasında
    #    seyahat edilebilir."
    #
    # The campaign runs 1-15 September, ticketing may be completed until 20
    # September, travel is October-December. Folded into two columns that reads
    # as one 1-20 September sale window, which is a claim neither sentence
    # makes.
    #
    # **What did NOT change, and why.** `sale_starts`/`sale_ends` remain the
    # SALE / RESERVATION window -- when a ticket can be bought -- exactly as
    # they always have. Renaming them to `booking_*` would have been the
    # tidier schema and was rejected: three writer paths and a four-figure test
    # suite are written against those names, `campaign_status()` reads them,
    # the timeline draws them, and the export ships them as `booking_start` /
    # `booking_end` to analysts' spreadsheets. A rename buys a better name and
    # costs a migration nobody can review.
    #
    # **When these four are written.** ONLY when the source states that window
    # *separately and explicitly*. A page that gives one window is giving the
    # sale window: it goes in `sale_*` and all four columns below stay NULL.
    # There is no inference, no copying `sale_ends` into `ticketing_end`, and
    # no defaulting -- NULL here means "the source did not state a separate
    # window", never "same as the sale window". `date_flags_json.explicit_dates`
    # records which edges were stated outright, so a reader can tell a stated
    # window from an absent one without re-reading the page.

    #: When the booked ticket has to be ISSUED/paid for. Distinct from the sale
    #: window on carriers that let you hold a reservation and pay later, which
    #: is precisely when the two dates differ and the difference is a deadline.
    ticketing_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    ticketing_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: The campaign's own announced run, when the page names one on top of the
    #: sale window -- "kampanya dönemi", "campaign period", "offer valid".
    campaign_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    campaign_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Idempotency key, same convention as aviation_events.url: the campaign
    # page for a scraped row, the article URL for an article-derived one.
    url: Mapped[str] = mapped_column(String(500), unique=True)
    source_name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    #: The news event this campaign was extracted from, when it came from an
    #: article rather than a scraped campaign page.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="SET NULL"), nullable=True
    )

    # --- validation and confidence ------------------------------------------
    #
    # 55% of what this table published was not a campaign: Etihad Rail tickets,
    # a Eurostar review, a Marriott points guide, an LNG pricing article, an
    # IAG Cargo revenue *decline* read as a 9% discount, and three rows whose
    # titles literally began "[Expired]". 92% had no sale date at all. The
    # columns below are how a row now has to earn its place on the page.

    #: valid | incomplete | rejected. Set by the campaign agent's validate()
    #: before anything is written, so an unvalidated row cannot exist.
    validation_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Read endpoints serve high and medium. A campaign missing its sale window
    #: is capped at medium by pipeline/confidence.py and, if it is missing more
    #: than half its required fields, at low -- which means invisible.
    confidence_band: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    confidence_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Soft delete. The 124 mis-extracted rows are marked rather than destroyed,
    #: so the before/after comparison stays checkable.
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

        # When WE first saw it -- not when the airline launched it. This is what
    # drives the "Yeni" badge and the 48h banner, and it is the only freshness
    # claim we can actually stand behind: an airline's own page carries no
    # publication timestamp, and a news report's date is the reporter's, not
    # the campaign's. Indexed because every list query orders or filters on it.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # --- campaign intelligence ----------------------------------------------
    #
    # Everything below is nullable and unwritten until the extraction chain
    # lands. A legacy row -- the ~200 already in the table -- keeps every one of
    # these NULL and keeps being served exactly as before; NULL here means "not
    # classified", never "classified as nothing". Nothing gets a server default
    # for the same reason: a default would make an untyped legacy row
    # indistinguishable from a row the classifier actually looked at.
    #
    # Note what is *not* here: status. UPCOMING / ACTIVE_BOOKING /
    # BOOKING_CLOSED_TRAVEL_ACTIVE / EXPIRED is a pure function of the date
    # columns and today's date, so it is computed at read time. Stored, it would
    # be wrong every morning until a cron caught up -- and this project's cron
    # is measurably 2-3 hours late.

    #: What kind of campaign it is (FLASH_SALE, SEASONAL, ROUTE_LAUNCH, ...).
    #: The analyst table's primary filter dimension. Validated in the app layer
    #: against app/taxonomy.py, not by a Postgres enum: the taxonomy will grow,
    #: and growing it should be a code change rather than a migration holding a
    #: lock on the table.
    campaign_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    #: CAMPAIGN (the offer is a price) or PROMOTION (the offer is a mechanism,
    #: a channel or an audience). Derived from `campaign_type` through
    #: taxonomy.CAMPAIGN_TYPE_TO_KIND, never detected separately -- see that
    #: table for why a second detector could only introduce disagreement.
    #:
    #: Stored rather than computed, which is the opposite call from `status`
    #: two paragraphs down, and for the opposite reason: a kind is a pure
    #: function of a *column* and so cannot go stale, while a status is a
    #: function of the clock and goes stale every midnight. Storing it is what
    #: lets the analyst list filter on it in SQL instead of re-deriving 27
    #: cases per row per query.
    #:
    #: NULL means undecidable -- an unclassified legacy row, or a row typed
    #: OTHER, where guessing a bucket would be worse than an empty cell.
    campaign_kind: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)

    #: The false-positive gate: ACTIVE_CAMPAIGN / EVERGREEN_OFFER / NEWS_ONLY /
    #: PRODUCT_PROMOTION / LOYALTY_PROMOTION. 55% of what this table once
    #: published was not a campaign at all, and the recurring shape of that
    #: error was a standing offer (student discount, corporate rate) or a
    #: product page (baggage, lounge) read as a limited-time sale. Separating
    #: "is it a campaign" from "what kind of campaign" is what lets the page
    #: show only the first class without deleting the rest.
    business_class: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    # --- route -------------------------------------------------------------
    #
    # How wide the campaign is matters more than which airports it names: a
    # network-wide sale and a single-OND promo fare are different competitive
    # events. Scope is recorded explicitly so a REGION campaign is never fanned
    # out into invented city pairs -- "Türkiye'den Avrupa'ya" is not IST-LHR.

    #: OND / CITY_PAIR / COUNTRY / REGION / NETWORK_WIDE.
    route_scope: Mapped[str | None] = mapped_column(String(12), nullable=True)
    #: "IST-LHR" -- the denormalised pair, set only when route_scope is OND.
    #: Indexed because the analyst's most common question is per-route.
    ond: Mapped[str | None] = mapped_column(String(9), nullable=True, index=True)
    origin_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    dest_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: The resolved detail behind the codes: {"origin": {airport, city, country,
    #: region}, "dest": {...}}. Kept next to the flat columns rather than
    #: replacing them, so a route filter never has to reach into JSON.
    route_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: The long tail of campaign terms -- cabin, promo_code, currency,
    #: price_floor, discount_type, sales_channel, eligibility, min/max stay,
    #: blackout_dates. JSON rather than twelve more columns: they are read
    #: together in the drawer, filtered on almost never, and the set of them
    #: keeps changing as carriers invent new fine print.
    attrs_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Per-field provenance: {field: {value, source_text, confidence}}. The
    #: drawer quotes source_text back at the reader, so "sale ends 30 Eylül" can
    #: be checked against the sentence it was taken from instead of trusted.
    #: This is the difference between a number and a citation.
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Why the classifier landed on this business_class/campaign_type, in one
    #: sentence. An unexplained rejection is unfixable.
    classification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Flagged for a human because confidence fell short. Indexed -- the review
    #: queue is a query. Nullable with no server default on purpose: a legacy
    #: row was never reviewed *and* never queued, which is neither True nor
    #: False.
    review_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    #: Two sources disagreed on a field and the more official one won. The
    #: losing value survives in the version row; this is just the badge.
    conflict_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: What we had to guess about the dates, e.g. {"inferred_year": true} when
    #: the page said "30 Eylül" with no year. Flagged rather than silently
    #: assumed, because a guessed year draws the same bar as a stated one.
    date_flags_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: The page's own dates, when it carries them -- distinct from detected_at,
    #: which is ours. A campaign page updated yesterday is news; one published
    #: in March and untouched since is an evergreen suspect.
    page_published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    page_updated_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: sha256 of the *extracted text*, not the raw HTML -- HTML churns on every
    #: request (session ids, timestamps, ad slots) while the campaign copy does
    #: not. This is the LLM budget: extraction only runs when the hash moves.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    #: The observation lifecycle, separate from detected_at (which is frozen at
    #: first sight and drives the "Yeni" badge). first_seen_at is backfilled
    #: from detected_at for legacy rows; last_seen_at moves every time a scan
    #: finds the campaign still on the page -- that is how an expiry is inferred
    #: for a campaign whose page never said when it ends; last_changed_at moves
    #: only when a field actually changed, so it is the version timeline's clock.
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The extracted page text the whole classification was derived from. Kept
    #: so a bad extraction can be re-run offline against the exact input,
    #: without re-fetching a page that may since have changed or gone behind a
    #: bot wall.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)


# How recently-detected a campaign has to be to still count as "new" on the
# timeline. Shared by the API and referenced by the frontend banner copy.
NEW_WINDOW_HOURS = 48
