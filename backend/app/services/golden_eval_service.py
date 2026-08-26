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

logger = get_logger(__name__)

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

        outcome = validate_campaign(record.title, campaign, today=today)
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
