from datetime import datetime

from pydantic import BaseModel


# WHY A PERCENT AND A POINT DIFFERENCE ARE TWO FIELDS AND NEVER ONE
#
# A load factor moving from 83.0 to 83.4 has two true readings: it rose 0.4
# POINTS, and it rose 0.48 PERCENT. Only the first is what an airline means by
# "load factor up 0.4", and printing the second behind a `%` sign -- which is
# what this schema used to carry, because `delta_pct` was the only field there
# was -- states a number nobody in revenue management would recognise, under
# the unit they do.
#
# So for a metric already denominated in points (`unit == "%"`), `delta_pct` is
# None and `delta_points` carries the difference. Not both: a payload offering
# two numbers for one movement is a payload inviting a surface to pick the
# wrong one, which is the disagreement this pair exists to end. Every other
# unit keeps `delta_pct` and leaves `delta_points` None.


class KpiOut(BaseModel):
    metric_key: str
    label: str
    value: float
    unit: str
    #: Percent change vs the previous observation -- None for a `%`-unit
    #: metric, which reports `delta_points` instead. See the note above.
    delta_pct: float | None
    #: Point change vs the previous observation, for `%`-unit metrics only.
    delta_points: float | None = None
    up_is_good: bool
    trend: list[float]
    is_estimate: bool
    as_of: datetime
    # Last-year (2025) comparison: the metric's 2025 value where one exists
    # (IATA's 2025 column, or the market price a year ago), else None.
    ly_value: float | None
    ly_delta_pct: float | None  # latest value vs ly_value, rounded to 2dp
    #: The same split as `delta_points`, applied to the last-year comparison.
    ly_delta_points: float | None = None
    comparison_label: str  # "2025 (LY)'e göre" when LY exists, else "önceki ölçüme göre"
    #: What period `value` describes: "2026 · tahmin" for an IATA annual
    #: figure, "son ölçüm" for a live reading. See PERIOD_KIND_LABELS_TR in
    #: app/api/v1/kpis.py.
    period_label: str | None = None


class KpiHistoryPointOut(BaseModel):
    as_of: datetime
    value: float


#: `KpiCorroborationOut.verdict` values.
CORROBORATION_MATCH = "match"
CORROBORATION_DIVERGES = "diverges"
#: The comparison could not be made at all -- see KpiCorroborationOut.diff_pct.
CORROBORATION_INCOMPARABLE = "incomparable"

CORROBORATION_VERDICT_LABELS_TR: dict[str, str] = {
    CORROBORATION_MATCH: "Eşleşiyor",
    CORROBORATION_DIVERGES: "Sapıyor",
    CORROBORATION_INCOMPARABLE: "Karşılaştırılamaz",
}


class KpiCorroborationOut(BaseModel):
    source: str
    source_url: str | None
    value: float
    #: When the CORROBORATING source's reading was taken. Compare it against
    #: `KpiDetailOut.as_of`, which is when the primary's was: two numbers from
    #: two different days are not a cross-check, however close they are.
    as_of: datetime
    #: |primary - this| as a percent of the primary -- or None when the two
    #: readings cannot be compared at all.
    #:
    #: None, and not 0.0. It used to be 0.0: an unusable primary value fell
    #: through to a default, and 0.0 read as "identical", so the screen printed
    #: "Eşleşiyor" over a comparison that had never happened. Optional is what
    #: makes "we did not check" expressible; `verdict` is what makes it
    #: readable.
    diff_pct: float | None = None
    #: "match" | "diverges" | "incomparable" -- decided HERE, not in the
    #: browser. The 0.5% rule lived in kpi-detail-client.tsx as a bare
    #: comparison, so the one claim this block makes was being made by the
    #: layer that draws it; a second surface reading the same payload was free
    #: to reach a different verdict. See CORROBORATION_MATCH_PCT.
    verdict: str = CORROBORATION_INCOMPARABLE
    verdict_label_tr: str = CORROBORATION_VERDICT_LABELS_TR[CORROBORATION_INCOMPARABLE]
    #: Why the comparison was refused, when it was: "no_primary_value" |
    #: "as_of_too_far_apart". None when `diff_pct` was computed.
    incomparable_reason: str | None = None


class KpiDetailOut(BaseModel):
    metric_key: str
    label: str
    value: float
    unit: str
    #: See the note above KpiOut: None for a `%`-unit metric.
    delta_pct: float | None
    #: Point change, for `%`-unit metrics only.
    delta_points: float | None = None
    up_is_good: bool
    is_estimate: bool
    as_of: datetime
    #: WHAT PERIOD `value` DESCRIBES, in Turkish.
    #:
    #: The field this page was missing. `/kpi/load_factor` serves IATA's 2026
    #: full-year FORECAST, and the page drew it exactly like Brent's last
    #: trade: one big number, one timestamp, no period -- so a projection for a
    #: year that has four months left to run read as this morning's
    #: measurement. `is_estimate` was on the payload the whole time and says
    #: only "this is not a direct reading"; it cannot say WHICH year, nor
    #: whether that year is forecast, estimate or closed.
    period_label: str | None = None
    #: What `delta_pct`/`delta_points` is measured against -- "2025'e göre" for
    #: an annual series, "önceki ölçüme göre" for a live one. Hardcoded in the
    #: browser until now, where it read "önceki ölçüme göre" over a
    #: year-on-year comparison.
    comparison_label: str | None = None
    source: str
    source_url: str | None
    corroborations: list[KpiCorroborationOut]
    #: The threshold `KpiCorroborationOut.verdict` was decided on, shipped so
    #: the page can state the rule beside the verdict instead of asserting it.
    corroboration_match_pct: float | None = None
    history: list[KpiHistoryPointOut]
    # True when `history` came from an external archive (Yahoo Finance, for
    # oil/FX); False when it's our own accumulated observations, which will be
    # sparse until the scheduler has run a while.
    #
    # KEPT, BUT NO LONGER THE WHOLE ANSWER: it is True for a derived history
    # too, and a deployed client reading only this field would still be told
    # "external". `history_provenance` is the field to read -- this one is
    # `history_provenance != OWN_HISTORY` and stays on the wire so an older
    # client does not break.
    history_is_external: bool
    #: "source_archive" | "derived_external" | "own_history". See
    #: HISTORY_PROVENANCE_NOTES_TR in app/api/v1/kpis.py.
    history_provenance: str = "own_history"
    #: The sentence the page prints under the chart, written where the
    #: derivation is known rather than reconstructed in the browser.
    history_provenance_tr: str | None = None
    period: str
