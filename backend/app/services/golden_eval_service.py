"""Faz 13: measuring the confidence system against the golden set, honestly
scoped to what each check can actually verify without new data collection.

Three checks, each covering a different slice of "does the pipeline get this
right", **not** a single per-surface hit rate -- the golden set (see
app/golden/__init__.py) only ever has a title and a link, never the article
body, so anything that needs the model's own judgment on real content needs
either a live LLM call over re-fetched content (`evaluate_full_pipeline`, the
only one of the three that costs tokens and network) or is out of reach
entirely for this data:

* `evaluate_campaign_guards` -- deterministic, no LLM, no fetch. Parses each
  campaign record's `system_label` (the OLD pipeline's own extraction: carrier
  · discount · dates) and runs it through validate_campaign()'s three guards.
  This can only ever explain the "bad" verdicts that were expired-title or
  implausible/stale-window mistakes -- attribution errors ("wrong carrier
  credited") are the model's job upstream of these guards and are not visible
  to a function that never sees who the model picked. Reported as exactly
  that: a lower bound on what the guards catch, not the campaign surface's
  overall accuracy.
* `evaluate_risk_country_normalisation` -- deterministic, no LLM, no fetch.
  Checks `_canonical_country()`-equivalent alias resolution (Turkish and
  English country names both landing on the same canonical key) against every
  country name actually named in a golden risk record's own label -- the
  specific bug class Faz 6 fixed (Turkish country names silently failing a
  bare English-keyed lookup). Does not test whether the model would have
  *found* that country in the first place; that step is inside the LLM call.
* `evaluate_full_pipeline` -- the real thing the plan describes: re-fetches
  each record's article body, runs the consolidated classifier, and grades the
  result against the golden verdict. Needs a configured LLM and working
  network access to the original sources (many golden links are dead or
  paywalled by now; those records are skipped and counted as such, not scored
  as failures). Returns None outright if no LLM is configured, so a local run
  with no key gets an honest "didn't run" instead of a fabricated zero.

PR8 adds a fourth, `evaluate_campaign_extraction` -- the precision/recall/
false-positive measurement the campaign quality gate is decided on. It is
documented at its own definition below, including exactly which parts of the
v2 chain it does and does not exercise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import httpx

from app.agents.campaign_airline import validate_campaign
from app.core.logging import get_logger
from app.golden import GoldenRecord, campaign_records, news_records, risk_records
from app.llm.classify import CampaignExtraction, classify_article
from app.llm.gazetteer import COUNTRY_ALIASES, fold_for_match
from app.pipeline.campaign_extract import resolve_route
from app.pipeline.promotions import find_dates_flagged, heuristic_extract
from app.services.campaign_status import campaign_status
from app.taxonomy import is_valid_campaign_type

logger = get_logger(__name__)

#: The clock the golden set is graded against. Fixed, not `date.today()`.
#:
#: The set is a snapshot: its labelled windows are the ones the sources
#: actually advertised, and every expired/stale/upcoming expectation on it is
#: a statement about where those windows sit relative to one specific day.
#: Grading it against a moving clock would make the headline KPI drift
#: overnight for reasons that have nothing to do with a code change -- a
#: campaign quietly crossing the 7-day staleness line would read as a
#: regression in the rulepacks. 2026-08-25 is the day the existing guard
#: regression in tests/test_golden_eval_service.py already pins, so the two
#: checks agree about when "now" is instead of drifting apart.
EVALUATION_TODAY = date(2026, 8, 25)

_LABEL_RE = re.compile(
    r"^(?P<code>[A-Z0-9]{2,3}) \([^)]+\) · (?P<discount>—|\d+%) · (?P<dates>.+)$"
)
_DATE_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})→(\d{4}-\d{2}-\d{2})$")


def _parse_campaign_label(label: str) -> CampaignExtraction | None:
    """The OLD pipeline's own extraction, as quoted in the golden record's
    `system_label` -- not a re-derivation, a parse of what's already there."""
    match = _LABEL_RE.match(label)
    if match is None:
        return None

    discount = match.group("discount")
    discount_pct = None if discount == "—" else int(discount.rstrip("%"))

    starts = ends = None
    date_range = _DATE_RANGE_RE.match(match.group("dates"))
    if date_range:
        starts = date.fromisoformat(date_range.group(1))
        ends = date.fromisoformat(date_range.group(2))

    return CampaignExtraction(
        airline_code=match.group("code"),
        discount_pct=discount_pct,
        sale_starts=starts,
        sale_ends=ends,
        travel_starts=None,
        travel_ends=None,
        markets={},
    )


@dataclass(frozen=True)
class GuardCheckResult:
    idx: int
    title: str
    golden_verdict: str
    guard_rejected: bool
    guard_reason: str | None
    unparseable: bool = False


@dataclass(frozen=True)
class CampaignGuardReport:
    results: list[GuardCheckResult]
    #: Of the golden "bad" records the guards could even parse, how many they
    #: correctly rejected. Not the campaign surface's overall accuracy -- see
    #: the module docstring on why attribution errors are invisible here.
    bad_records_parsed: int
    bad_records_caught: int
    #: The two real "ok" records must NOT be rejected by the guards -- a
    #: false positive here is the guards being too aggressive, not too weak.
    ok_records_wrongly_rejected: int


def evaluate_campaign_guards(
    records: list[GoldenRecord] | None = None, *, today: date | None = None
) -> CampaignGuardReport:
    """Every record's label through the three date guards and the rulepacks.

    `record.text` is passed where a record has one (the PR8 authored subset);
    observed records have no body and are graded on their title exactly as
    before, so their verdicts are unchanged by the set's expansion.
    """
    records = records if records is not None else campaign_records()
    results: list[GuardCheckResult] = []

    for record in records:
        campaign = _parse_campaign_label(record.system_label)
        if campaign is None:
            results.append(
                GuardCheckResult(
                    idx=record.idx,
                    title=record.title,
                    golden_verdict=record.verdict,
                    guard_rejected=False,
                    guard_reason=None,
                    unparseable=True,
                )
            )
            continue

        outcome = validate_campaign(record.title, campaign, today=today, text=record.text)
        results.append(
            GuardCheckResult(
                idx=record.idx,
                title=record.title,
                golden_verdict=record.verdict,
                guard_rejected=not outcome.is_classified,
                guard_reason=None if outcome.is_classified else outcome.reason,
            )
        )

    bad_parsed = [r for r in results if r.golden_verdict == "bad" and not r.unparseable]
    return CampaignGuardReport(
        results=results,
        bad_records_parsed=len(bad_parsed),
        bad_records_caught=sum(1 for r in bad_parsed if r.guard_rejected),
        ok_records_wrongly_rejected=sum(
            1 for r in results if r.golden_verdict == "ok" and r.guard_rejected
        ),
    )


# --- PR8: the campaign quality gate -----------------------------------------


@dataclass(frozen=True)
class ExtractionCheckResult:
    """One record's trip through the deterministic half of the v2 chain."""

    idx: int
    title: str
    golden_verdict: str
    synthetic: bool
    #: The gate's own question: would this row reach the published campaign
    #: timeline? That is `validate_campaign()`'s verdict and nothing else --
    #: see the evaluator's docstring on why status is not folded in.
    would_publish: bool
    reason: str | None
    detected_business_class: str | None
    expected_business_class: str | None
    resolved_route_scope: str | None
    expected_route_scope: str | None
    computed_status: str | None
    expected_status: str | None
    #: Date fields the record stated an expectation for, and how many of those
    #: the deterministic reader put in the right column.
    date_fields_checked: int = 0
    date_fields_correct: int = 0
    #: Expected date *values* the regex layer can find in the body at all --
    #: the gate `verify_dates()` puts in front of every model-supplied date.
    date_values_checked: int = 0
    date_values_found: int = 0
    unparseable: bool = False


@dataclass(frozen=True)
class BusinessClassBreakdown:
    """Per expected business_class: did anything leak, and was it recognised
    as the right kind of wrong?"""

    total: int
    #: How many of them reach the timeline. Which way this should point is the
    #: class's own answer: ACTIVE_CAMPAIGN wants all of them, and every other
    #: class in CAMPAIGN_BUSINESS_CLASSES wants none -- for those, this is the
    #: leak count, and it is the number the false-positive gate is made of.
    published: int
    #: How many rows the pipeline agreed with about *which kind* of row this
    #: is. A row rejected as PRODUCT_PROMOTION when the label says NEWS_ONLY
    #: is still correctly kept off the timeline -- counted here so the
    #: disagreement is visible rather than hidden behind "0 leaked".
    class_agreed: int

    @property
    def publish_rate(self) -> float | None:
        return self.published / self.total if self.total else None


@dataclass(frozen=True)
class CampaignExtractionReport:
    results: list[ExtractionCheckResult]
    today: date

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    warn_excluded: int
    unparseable: int

    by_business_class: dict[str, BusinessClassBreakdown]

    campaign_type_checked: int
    campaign_type_valid: int
    route_scope_checked: int
    route_scope_correct: int
    date_fields_checked: int
    date_fields_correct: int
    date_values_checked: int
    date_values_found: int
    status_checked: int
    status_correct: int

    @property
    def graded(self) -> int:
        return (
            self.true_positives
            + self.false_positives
            + self.false_negatives
            + self.true_negatives
        )

    @property
    def precision(self) -> float | None:
        published = self.true_positives + self.false_positives
        return self.true_positives / published if published else None

    @property
    def recall(self) -> float | None:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def false_positive_rate(self) -> float | None:
        """**The gate.** Of every record the judge called `bad`, the share the
        pipeline would still publish. Not 1 - precision: the denominator is
        the bad population, so the number answers "how much of the wrong stuff
        gets through" independently of how much right stuff there is."""
        bad = self.false_positives + self.true_negatives
        return self.false_positives / bad if bad else None

    def _ratio(self, correct: int, checked: int) -> float | None:
        return correct / checked if checked else None

    @property
    def campaign_type_accuracy(self) -> float | None:
        return self._ratio(self.campaign_type_valid, self.campaign_type_checked)

    @property
    def route_scope_accuracy(self) -> float | None:
        return self._ratio(self.route_scope_correct, self.route_scope_checked)

    @property
    def date_field_accuracy(self) -> float | None:
        return self._ratio(self.date_fields_correct, self.date_fields_checked)

    @property
    def date_corroboration(self) -> float | None:
        return self._ratio(self.date_values_found, self.date_values_checked)

    @property
    def status_accuracy(self) -> float | None:
        return self._ratio(self.status_correct, self.status_checked)


def _extraction_for(
    record: GoldenRecord, campaign: CampaignExtraction
) -> CampaignExtraction:
    """What a correct extraction of this record looks like, as far as code
    alone can get.

    For an observed record that is the label itself (the same parse
    `evaluate_campaign_guards` grades). For an authored record it is the
    deterministic reader run over the real body: `heuristic_extract()` is the
    regex layer that `campaign_extract.verify_dates()` cross-checks every
    model-supplied date against, so a window it cannot find is a window the v2
    chain would not corroborate either. The airline code still comes from the
    label -- attribution is the model's answer, not a regex's.
    """
    if not record.text:
        return campaign

    fields = heuristic_extract(record.title, record.text, EVALUATION_TODAY.year)
    return CampaignExtraction(
        airline_code=campaign.airline_code,
        discount_pct=fields.discount_pct if fields.discount_pct is not None else campaign.discount_pct,
        sale_starts=fields.sale_starts,
        sale_ends=fields.sale_ends,
        travel_starts=fields.travel_starts,
        travel_ends=fields.travel_ends,
        markets={},
    )


#: The three business classes taxonomy.py derives from *dates* rather than
#: detecting. agents/campaign_airline.py deliberately leaves `business_class`
#: null on its three date guards ("the date guards are not business-class
#: verdicts, and services/campaign_status.py owns the EXPIRED question"), so
#: grading them against the detected class would fail every one of them for
#: doing exactly what they are documented to do. They are graded against the
#: status engine instead, which is where that answer actually lives.
_STATUS_FOR_DATE_DERIVED_CLASS: dict[str, str] = {
    "EXPIRED_CAMPAIGN": "EXPIRED",
    "UPCOMING_CAMPAIGN": "UPCOMING",
}


def _class_agrees(result: ExtractionCheckResult, expected: str) -> bool:
    status = _STATUS_FOR_DATE_DERIVED_CLASS.get(expected)
    if status is not None:
        return result.computed_status == status
    return result.detected_business_class == expected


def _grade_dates(record: GoldenRecord, actual: CampaignExtraction) -> tuple[int, int, int, int]:
    """(fields_checked, fields_correct, values_checked, values_found)."""
    expected = record.expected_dates()
    got = {
        "sale_starts": actual.sale_starts,
        "sale_ends": actual.sale_ends,
        "travel_starts": actual.travel_starts,
        "travel_ends": actual.travel_ends,
    }
    stated = {key: value for key, value in expected.items() if value is not None}
    fields_correct = sum(1 for key, value in stated.items() if got[key] == value)

    values_found = 0
    if record.text:
        in_text = {
            parsed
            for _offset, parsed, _inferred in find_dates_flagged(
                f"{record.title}\n{record.text}", EVALUATION_TODAY.year
            )
        }
        values_found = sum(1 for value in stated.values() if value in in_text)

    return len(stated), fields_correct, len(stated) if record.text else 0, values_found


def evaluate_campaign_extraction(
    records: list[GoldenRecord] | None = None, *, today: date | None = None
) -> CampaignExtractionReport:
    """Precision, recall and the false-positive rate for the campaign surface.

    What this runs
    --------------
    The deterministic half of the v2 chain, end to end: the date reader
    (`pipeline/promotions.heuristic_extract`, built on `find_dates_flagged`),
    the rulepacks and the three date guards (`validate_campaign`), the route
    resolver (`pipeline/campaign_extract.resolve_route`) and the status engine
    (`services/campaign_status.campaign_status`). No LLM call, no network, so
    it runs in CI and in a local `pytest` with no key configured.

    What it therefore cannot claim
    ------------------------------
    The same honesty `evaluate_campaign_guards` states for itself, and for the
    same reason: extraction is the model's job, and a function that never
    calls the model cannot grade it. Concretely --

    * The **publish decision** measured here is `validate_campaign()`'s, taken
      over an item extracted as correctly as code alone can manage. It is a
      *lower bound on the damage a wrong extraction can do*: if the model
      hands the guards a correct campaign, this is what happens to it. A model
      that invents a discount or credits the wrong carrier fails upstream of
      everything measured here, and `evaluate_full_pipeline` is the check that
      costs tokens because it is the only one that can see that.
    * `campaign_type_accuracy` is **not** a model-accuracy number and must not
      be quoted as one. Nothing deterministic picks a campaign_type -- the
      only code-level step is `taxonomy.is_valid_campaign_type()`, the closed
      set that decides whether a correctly-chosen type survives into the row.
      So this measures taxonomy retention: it goes red when a slug the golden
      set expects is renamed or dropped out from under it, and it can never go
      red for a bad model call. It is reported with that caption attached.
    * `route_scope_accuracy`, `date_field_accuracy`, `date_corroboration` and
      `status_accuracy` *are* real: every one of them is produced by code that
      ships, run over the record's own words.

    Grading
    -------
    Positive class is "would reach the published campaign timeline". `warn`
    records are excluded (the judge's own uncertainty; forcing them into
    agree/disagree would manufacture precision, the same call `_evaluate_golden`
    already makes for the full-pipeline pass). Records whose label will not
    parse are counted as `unparseable` and excluded -- there is no extraction
    to grade, and scoring them either way would be inventing a result.

    Status is deliberately *not* folded into the publish decision. A campaign
    whose sale window closed three days ago is still published, rendered
    "Süresi doldu"; the timeline showing what just ended is a feature, not a
    leak. `validate_campaign()`'s 7-day staleness guard is the real boundary,
    so it is the one measured.
    """
    reference = today or EVALUATION_TODAY
    records = records if records is not None else campaign_records()
    results: list[ExtractionCheckResult] = []

    for record in records:
        parsed = _parse_campaign_label(record.system_label)
        if parsed is None:
            results.append(
                ExtractionCheckResult(
                    idx=record.idx,
                    title=record.title,
                    golden_verdict=record.verdict,
                    synthetic=record.is_synthetic,
                    would_publish=False,
                    reason=None,
                    detected_business_class=None,
                    expected_business_class=record.expected_business_class,
                    resolved_route_scope=None,
                    expected_route_scope=record.expected_route_scope,
                    computed_status=None,
                    expected_status=record.expected_status,
                    unparseable=True,
                )
            )
            continue

        extraction = _extraction_for(record, parsed)
        outcome = validate_campaign(
            record.title, extraction, today=reference, text=record.text
        )
        route = resolve_route(
            record.expected_origin,
            record.expected_destination,
            text=f"{record.title}\n{record.text or ''}",
        )
        fields_checked, fields_correct, values_checked, values_found = _grade_dates(
            record, extraction
        )

        results.append(
            ExtractionCheckResult(
                idx=record.idx,
                title=record.title,
                golden_verdict=record.verdict,
                synthetic=record.is_synthetic,
                would_publish=outcome.is_classified,
                reason=None if outcome.is_classified else outcome.reason,
                detected_business_class=outcome.details.get("business_class"),
                expected_business_class=record.expected_business_class,
                resolved_route_scope=route.scope,
                expected_route_scope=record.expected_route_scope,
                computed_status=campaign_status(
                    extraction.sale_starts,
                    extraction.sale_ends,
                    extraction.travel_starts,
                    extraction.travel_ends,
                    reference,
                ),
                expected_status=record.expected_status,
                date_fields_checked=fields_checked,
                date_fields_correct=fields_correct,
                date_values_checked=values_checked,
                date_values_found=values_found,
            )
        )

    graded = [r for r in results if r.golden_verdict in ("ok", "bad") and not r.unparseable]

    by_class: dict[str, BusinessClassBreakdown] = {}
    for expected in sorted({r.expected_business_class for r in results if r.expected_business_class}):
        rows = [r for r in results if r.expected_business_class == expected]
        by_class[expected] = BusinessClassBreakdown(
            total=len(rows),
            published=sum(1 for r in rows if r.would_publish),
            class_agreed=sum(1 for r in rows if _class_agrees(r, expected)),
        )

    typed = [r for r in records if r.expected_campaign_type]
    scoped = [r for r in results if r.expected_route_scope and not r.unparseable]
    with_status = [r for r in results if r.expected_status and not r.unparseable]

    return CampaignExtractionReport(
        results=results,
        today=reference,
        true_positives=sum(1 for r in graded if r.golden_verdict == "ok" and r.would_publish),
        false_positives=sum(1 for r in graded if r.golden_verdict == "bad" and r.would_publish),
        false_negatives=sum(1 for r in graded if r.golden_verdict == "ok" and not r.would_publish),
        true_negatives=sum(1 for r in graded if r.golden_verdict == "bad" and not r.would_publish),
        warn_excluded=sum(1 for r in results if r.golden_verdict == "warn"),
        unparseable=sum(1 for r in results if r.unparseable),
        by_business_class=by_class,
        campaign_type_checked=len(typed),
        campaign_type_valid=sum(1 for r in typed if is_valid_campaign_type(r.expected_campaign_type)),
        route_scope_checked=len(scoped),
        route_scope_correct=sum(
            1 for r in scoped if r.resolved_route_scope == r.expected_route_scope
        ),
        date_fields_checked=sum(r.date_fields_checked for r in results),
        date_fields_correct=sum(r.date_fields_correct for r in results),
        date_values_checked=sum(r.date_values_checked for r in results),
        date_values_found=sum(r.date_values_found for r in results),
        status_checked=len(with_status),
        status_correct=sum(1 for r in with_status if r.computed_status == r.expected_status),
    )


# A few Turkish country names that show up in this specific golden set's
# labels but aren't necessarily in gazetteer.py's curated Turkish list --
# added here only to widen what this check can grade, never to widen the
# gazetteer itself (see app/llm/gazetteer.py for why that list stays curated).
_EXTRA_COUNTRY_LABELS: dict[str, str] = {
    "ukraine": "ukraine",
    "ukrayna": "ukraine",
    "russia": "russia",
    "rusya": "russia",
}


@dataclass(frozen=True)
class CountryCheckResult:
    idx: int
    stated_country: str
    resolved: bool


@dataclass(frozen=True)
class CountryNormalisationReport:
    results: list[CountryCheckResult]
    checked: int
    resolved: int


#: The judge's own marker for "no country was stated" -- not a country name
#: to fail resolving, so it must not be counted as a checked case at all.
_NO_COUNTRY_MARKER = "belirtilmemiş"


def _extract_stated_country(system_label: str) -> str | None:
    """Golden risk labels read "attack (high) · Ukraine" or, with a city,
    "war (high) · India · Mumbai" -- country is always the second field,
    city (if any) the third."""
    parts = system_label.split(" · ")
    if len(parts) < 2:
        return None
    country = parts[1].strip()
    if not country or country.lower() == _NO_COUNTRY_MARKER:
        return None
    return country


def evaluate_risk_country_normalisation(
    records: list[GoldenRecord] | None = None,
) -> CountryNormalisationReport:
    records = records if records is not None else risk_records()
    results: list[CountryCheckResult] = []

    for record in records:
        country = _extract_stated_country(record.system_label)
        if not country:
            continue
        folded = fold_for_match(country)
        canonical = COUNTRY_ALIASES.get(folded) or _EXTRA_COUNTRY_LABELS.get(folded)
        results.append(
            CountryCheckResult(idx=record.idx, stated_country=country, resolved=canonical is not None)
        )

    return CountryNormalisationReport(
        results=results,
        checked=len(results),
        resolved=sum(1 for r in results if r.resolved),
    )


@dataclass(frozen=True)
class FullPipelineRecordResult:
    idx: int
    surface: str
    golden_verdict: str
    #: Whether the live classifier's CLASSIFIED/NOT_APPLICABLE call agrees with
    #: the golden verdict (ok -> should classify, bad -> should not). Not a
    #: confidence-band calibration -- that number needs pipeline/confidence.py's
    #: full inputs (source tier, corroboration count), which only exist once an
    #: event is actually being assembled by app/agents/runner.py, not from one
    #: classify_article() call in isolation.
    classified: bool


@dataclass
class FullPipelineReport:
    surface: str
    results: list[FullPipelineRecordResult] = field(default_factory=list)
    skipped_no_url: int = 0
    skipped_fetch_failed: int = 0


async def _fetch_content(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (AeroIntel golden-eval)"})
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        logger.warning("golden_eval_fetch_failed", url=url, error=str(exc))
        return None


async def evaluate_full_pipeline(
    records: list[GoldenRecord] | None = None, *, surface: str = "news"
) -> FullPipelineReport | None:
    """Re-fetches each record's article and runs the live consolidated
    classifier. Returns None without doing anything if no LLM is configured --
    a local run with no key gets an honest "didn't run", never a fabricated
    report. Costs one LLM call and one HTTP fetch per record with a URL."""
    from app.llm.factory import get_raw_generator

    if get_raw_generator() is None:
        return None

    records = records if records is not None else (
        {"risk": risk_records, "news": news_records, "campaign": campaign_records}[surface]()
    )
    report = FullPipelineReport(surface=surface)

    for record in records:
        if not record.url:
            report.skipped_no_url += 1
            continue

        content = await _fetch_content(record.url)
        if content is None:
            report.skipped_fetch_failed += 1
            continue

        result = await classify_article(record.title, content)
        if surface == "risk":
            classified = result.risk.is_classified
        elif surface == "campaign":
            classified = result.campaign.is_classified
        else:
            classified = result.article.is_classified

        report.results.append(
            FullPipelineRecordResult(
                idx=record.idx,
                surface=surface,
                golden_verdict=record.verdict,
                classified=classified,
            )
        )

    return report
