"""The golden set: 255 hand-judged records (24 risk, 100 news, 131 campaign)
behind Faz 13's calibration.

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
"""
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class GoldenRecord:
    idx: int
    title: str
    system_label: str
    verdict: str  # ok | bad | warn
    reason: str
    source: str
    url: str | None


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
