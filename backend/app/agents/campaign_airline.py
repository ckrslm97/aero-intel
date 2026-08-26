"""Turning a classified campaign extraction into a validated Promotion row.

The measured failure this exists to fix: of 131 rows the old pipeline
published, only 2 were genuine, correctly-attributed, dated fare campaigns.
The rest were loyalty-programme guides, credit-card point transfers, hotel and
rail content, a revenue *decline* read as a discount, and rows whose titles
began "[Expired]" -- because the candidate gate inherited whatever the news
categoriser decided (see the "revenue_management/pricing" bucket in
taxonomy.py), and attribution took "whichever tracked carrier is mentioned
most", ordered on a column (`ArticleEntity.relevance`) that was never written.

Neither mistake is structurally possible here. The candidate is the event the
consolidated classifier already decided *is* a campaign (llm/classify.py's
`is_campaign` verdict, with its own veto -- "not a campaign" is a real,
recorded answer, not a gap the old gate filled with a guess). Attribution is
the model's direct answer to "who is running this", not a mention count over a
column nothing populated.

What this module adds on top of the model's verdict is two code-level guards
for exactly the patterns still found live in production after that fix:

* **Expired titles.** The prompt already tells the model a `[Expired]` title
  is not a live campaign, and it mostly listens -- but "mostly" is not the bar
  for a boolean the reader trusts, so it is enforced here too, the same way
  llm/classify.py range-checks `discount_pct` instead of only asking nicely.
* **Implausible sale windows.** Two live rows had 2024-06-25 -> 2026-12-31 and
  2024-10-15 -> 2026-08-31 as their "sale window" -- partnership announcements
  with no real booking deadline, mislabelled as campaigns with a start date and
  an end date because both happened to appear somewhere in the text. A real
  fare sale's booking window is days, not years.

Validated fields become a `Promotion` row's completeness for
pipeline/confidence.py: `sale_starts or sale_ends` is the one genuinely
variable required field (airline_code is guaranteed by the parser, url by the
article always having one) -- missing it caps the row at the low band, which
is how "eksikse yayınlama" is actually enforced rather than merely stated.
"""
from __future__ import annotations

from datetime import date, datetime

from app.llm.classify import CampaignExtraction
from app.llm.gazetteer import AIRLINE_ALIASES
from app.models.article import Article
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
from app.pipeline.confidence import ConfidenceInput, score
from app.pipeline.outcomes import Outcome

#: A booking window wider than this is not a fare sale; it is something else
#: wearing a fare sale's two date fields. 120 days was the figure the plan
#: settled on, wide enough to cover a real multi-week campaign with room to
#: spare, narrow enough to reject the multi-year "iş birliği" rows.
MAX_SALE_WINDOW_DAYS = 120

#: A campaign whose sale window closed this long ago is stale enough that
#: showing it as live would be misleading, even though the extraction itself
#: was accurate at the time.
STALE_AFTER_DAYS = 7

_EXPIRED_MARKERS = ("[expired]", "[deal alert]", "süresi doldu", "süresi bitti")

_AIRLINE_NAME_BY_CODE: dict[str, str] = {
    code: name for name, code in AIRLINE_ALIASES.values()
}

REQUIRED_FIELDS = ("sale_window",)


def _looks_expired(title: str) -> bool:
    folded = (title or "").lower()
    return any(marker in folded for marker in _EXPIRED_MARKERS)


def _window_is_implausible(starts: date | None, ends: date | None) -> bool:
    if starts is None or ends is None:
        return False
    return (ends - starts).days > MAX_SALE_WINDOW_DAYS


def _window_is_stale(ends: date | None, *, today: date) -> bool:
    if ends is None:
        return False
    return (today - ends).days > STALE_AFTER_DAYS


def validate_campaign(
    title: str, campaign: CampaignExtraction, *, today: date | None = None
) -> Outcome[CampaignExtraction]:
    """The second validation layer, on top of the model's own verdict.

    Downgrades a CLASSIFIED campaign to NOT_APPLICABLE when it matches one of
    the two patterns still reaching production after the model-level fix.
    Never upgrades or invents -- this only ever narrows what the model already
    said yes to.
    """
    reference = today or date.today()

    if _looks_expired(title):
        return Outcome.not_applicable("expired_title")

    if _window_is_implausible(campaign.sale_starts, campaign.sale_ends):
        return Outcome.not_applicable("implausible_sale_window")

    if _window_is_stale(campaign.sale_ends, today=reference):
        return Outcome.not_applicable("sale_window_closed")

    return Outcome.classified(campaign)


def build_promotion(
    *,
    event: NewsEvent,
    primary: Article,
    campaign: CampaignExtraction,
    certainty: float | None,
    source_tier: str,
    source_count: int,
    detected_at: datetime,
) -> Promotion:
    """Construct the row. Caller commits; `event.id` must already be flushed.

    `detected_at` is "when WE first saw it" (see the column's own docstring on
    Promotion) -- the pipeline run's timestamp, passed in rather than read from
    the clock here, so every row this run writes agrees on when "now" was.
    """
    has_sale_window = campaign.sale_starts is not None or campaign.sale_ends is not None
    confidence = score(
        ConfidenceInput(
            source_tier=source_tier,
            classifier_certainty=certainty,
            required_fields_present=1 if has_sale_window else 0,
            required_fields_total=1,
            signal_agreement=None,
            source_count=source_count,
        )
    )

    airline_name = _AIRLINE_NAME_BY_CODE.get(campaign.airline_code, campaign.airline_code)

    return Promotion(
        airline_code=campaign.airline_code,
        airline_name=airline_name,
        title_tr=event.title_tr or primary.title,
        summary_tr=event.summary_tr or "",
        discount_pct=campaign.discount_pct,
        markets_json=campaign.markets or None,
        sale_starts=campaign.sale_starts,
        sale_ends=campaign.sale_ends,
        travel_starts=campaign.travel_starts,
        travel_ends=campaign.travel_ends,
        url=primary.url,
        source_name=primary.source.name if primary.source else "",
        region=event.region,
        event_id=event.id,
        validation_state="valid" if has_sale_window else "incomplete",
        confidence_score=confidence.score,
        confidence_band=confidence.band,
        confidence_detail=confidence.as_detail(),
        detected_at=detected_at,
    )
