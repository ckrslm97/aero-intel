"""The golden set: 315 records (24 risk, 100 news, 191 campaign) -- 255
hand-judged snapshots of live production output plus 60 synthetic
campaign-surface records: 42 authored for the PR8 quality gate, 14 pinning the
award/cargo/service-announcement patterns that were still reaching the live
timeline after the backfill retired the legacy rows, and 4 pinning both
directions of the ancillary rule.

`golden_set.json` is a snapshot of the owner-reviewed evaluation page
(https://claude.ai/code/artifact/fba3334f-3f64-4ac1-bdf0-7be6cff45e83),
trimmed to the fields a grader needs: `verdict` (ok/bad/warn -- the judge's
call on whether the OLD v1 pipeline's `system_label` was right),  `reason`
(why), and enough of the original record to re-derive a check against.

This is not a {input, correct_output} pair set for the new pipeline: it only
ever has a title and a link, never the article body, and `system_label` is
what the OLD, broken pipeline produced -- not what v2 should produce. What it
does support without any further data collection: deterministic checks that
only need the title text or the label's own quoted fields (see
app/services/golden_eval_service.py's guard-level and country-resolution
checks). A full per-surface hit rate against the live v2 classifier needs the
article body (re-fetched from `url`, where one exists) and a configured LLM --
see `evaluate_full_pipeline`, which is the part of this module that cannot run
without both.

The synthetic campaign records
------------------------------
The 56 records carrying a `source` in `SYNTHETIC_SOURCES` are a different kind
of data and are deliberately marked as such on every row. They are **authored,
not observed**: realistic Turkish and English airline-campaign copy written to
cover the dimensions the v2 chain added (campaign_type, business_class,
route_scope, English and year-less dates, booking-vs-travel separation,
near-duplicates) and which the 2025 production snapshot simply does not
contain -- it is 131 rows from one static-scrapable carrier, 99 of them wrong
in four repeating ways.

The `synthetic-ancillary` batch is the same idea applied to a widening rather
than a leak: it exists so that "an ancillary offer tied to a flight purchase is
publishable" cannot quietly become "ancillary offers are publishable".

The `synthetic-leaks` batch has a narrower job: each of its 12 "bad" records
is a paraphrase of a row that was *still live on the site* after the backfill
retired 121 of 144 legacy rows -- award-sale and award-booking content, a
cargo division's half-year revenue report, an onboard-service launch -- and
each one exists so that closing that leak stays closed. Its two "ok" records
are the other half of the same argument: a genuine dated fare campaign that
calls itself an "ödüllü havayolu" ("award-winning airline") must still be
published, because a rulepack that keys on "ödül" without knowing Turkish
morphology would silently start rejecting real campaigns for praising
themselves.

Because they are authored, they carry what an observed record cannot: a
`text` body and explicit `expected_*` fields stating the correct answer.
That is what makes a precision/recall/false-positive measurement possible at
all (see `evaluate_campaign_extraction`), and it is also their limitation --
a synthetic record proves the rulepacks behave as designed on copy shaped like
this, not that real carrier pages are shaped like this. The `source` marker
exists so no reader, and no future evaluator, can confuse the two populations;
`synthetic_campaign_records()` and `observed_campaign_records()` split them.

Every field below `url` is optional and defaults to None, so the 255 observed
records load byte-for-byte unchanged -- the schema grew additively rather than
being versioned.
"""
import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent

#: The `source` marker on the PR8 authored records. See the module docstring.
SYNTHETIC_SOURCE = "synthetic-pr8"

#: The second authored batch, added when the rulepacks were widened for the
#: award/cargo/service-announcement leaks that survived the backfill. Marked
#: with its own source rather than folded into "synthetic-pr8" so the reason a
#: record exists stays readable on the row: these 14 are regression pins for
#: specific patterns that were live on the site, not coverage for a dimension
#: the snapshot lacks.
SYNTHETIC_LEAK_SOURCE = "synthetic-leaks"

#: The third authored batch, added when PRODUCT_PROMOTION stopped being an
#: unconditional rejection. Four records, two each way, because the change makes
#: the false-positive gate *looser* and a rule that only ever gets tested in the
#: direction it was widened is a rule nobody is guarding: two ancillary offers
#: explicitly conditional on buying a flight ("bilet alana 10 kg ekstra bagaj",
#: "complimentary lounge access when you book a flight") that must now be
#: published, and two standalone ones (a hotel-booking discount, a lounge
#: membership sale) that must still be rejected.
SYNTHETIC_ANCILLARY_SOURCE = "synthetic-ancillary"

#: Every marker that means "authored, not observed". `is_synthetic` reads this
#: rather than one constant, so the observed/authored split -- which is what
#: keeps the 131-row production snapshot honest -- never depends on remembering
#: to update two places when a batch is added.
SYNTHETIC_SOURCES: frozenset[str] = frozenset(
    {SYNTHETIC_SOURCE, SYNTHETIC_LEAK_SOURCE, SYNTHETIC_ANCILLARY_SOURCE}
)


@dataclass(frozen=True, slots=True)
class GoldenRecord:
    idx: int
    title: str
    system_label: str
    verdict: str  # ok | bad | warn
    reason: str
    source: str
    url: str | None

    # --- authored-record extensions (PR8) ---------------------------------
    #
    # All optional. An observed record has none of them and behaves exactly as
    # it did before they existed.

    #: The article/page body. Observed records never have one (the snapshot
    #: kept titles and links only), which is why every check that needs a body
    #: is scoped to the authored subset.
    text: str | None = None
    expected_campaign_type: str | None = None
    expected_business_class: str | None = None
    expected_route_scope: str | None = None
    #: Origin/destination as the page words them -- the strings a correct
    #: extraction would hand to `resolve_route()`. Stored raw rather than
    #: pre-resolved so the resolver, not the label, is what gets graded.
    expected_origin: str | None = None
    expected_destination: str | None = None
    expected_sale_starts: str | None = None
    expected_sale_ends: str | None = None
    expected_travel_starts: str | None = None
    expected_travel_ends: str | None = None
    expected_status: str | None = None
    #: Set on records that are two framings of the same campaign; shared value
    #: means the dedup layer should collapse them into one row.
    dedup_group: str | None = None

    @property
    def is_synthetic(self) -> bool:
        return self.source in SYNTHETIC_SOURCES

    def expected_dates(self) -> dict[str, date | None]:
        """The four date expectations as dates, keyed like the columns."""
        return {
            "sale_starts": _as_date(self.expected_sale_starts),
            "sale_ends": _as_date(self.expected_sale_ends),
            "travel_starts": _as_date(self.expected_travel_starts),
            "travel_ends": _as_date(self.expected_travel_ends),
        }


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@cache
def _raw() -> dict:
    with (_DATA_DIR / "golden_set.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _records(surface: str) -> list[GoldenRecord]:
    return [GoldenRecord(**row) for row in _raw()[surface]]


@cache
def risk_records() -> list[GoldenRecord]:
    return _records("risk")


@cache
def news_records() -> list[GoldenRecord]:
    return _records("news")


@cache
def campaign_records() -> list[GoldenRecord]:
    return _records("campaign")


@cache
def synthetic_campaign_records() -> list[GoldenRecord]:
    """The authored subset -- the only records with a body and expectations."""
    return [record for record in campaign_records() if record.is_synthetic]


@cache
def observed_campaign_records() -> list[GoldenRecord]:
    """The 2025 production snapshot, unchanged since Faz 13."""
    return [record for record in campaign_records() if not record.is_synthetic]
