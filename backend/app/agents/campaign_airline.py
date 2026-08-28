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

The business-class layer
------------------------
The two guards above ask "is this campaign live and plausible". They cannot
ask the prior question -- "is this a fare campaign at all" -- because both of
them pass a page with no dates on it, and most of the 129 wrong rows had no
dates. That question is what `_business_class()` answers, with keyword
rulepacks rather than another model call: the four wrong kinds are lexically
obvious (a mileage sale says "miles", a baggage promo says "bagaj", a student
page says "öğrenci"), they are the same four kinds every time, and a rulepack
is auditable in a way a second LLM verdict is not.

Only the "is this a fare campaign" half of `business_class` is decided here.
ACTIVE/UPCOMING/EXPIRED_CAMPAIGN is a *date* question, answered by
services/campaign_status.py from the same four columns the UI reads, and
duplicating that here would give one row two answers that drift apart the
moment the clock moves. A page that passes every guard is ACTIVE_CAMPAIGN in
the sense that matters here: a real fare campaign, whose position in time is
computed elsewhere.

Every verdict, positive or negative, carries a `classification_reason` -- one
honest Turkish sentence saying what the decision was based on. It rides in the
Outcome's `details` dict rather than in a new return type, because that is the
mechanism already in place and existing callers (agents/runner.py,
services/golden_eval_service.py) go on reading `.payload`/`.reason` unchanged.
"""
from __future__ import annotations

from datetime import date, datetime

from app.agents.gate import DISTRACTOR_TERMS
from app.core.tr_dates import format_optional_range
from app.llm.classify import CampaignExtraction
from app.llm.gazetteer import AIRLINE_ALIASES
from app.llm.heuristic import _keyword_pattern, fold_text
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

# --- business-class rulepacks ------------------------------------------------
#
# Written in fold_text() form: ASCII, lowercase, Turkish diacritics mapped onto
# their bases and every non-alphanumeric character collapsed to a space. So
# "öğrenci" is "ogrenci" and "Miles&Smiles" is "miles smiles". Writing them any
# other way would silently never match -- the same trap agents/gate.py
# documents at the top of its own tables.

#: Standing benefits with no campaign window: a segment that always gets this
#: rate. A published "campaign" that never starts and never ends is noise on a
#: timeline whose entire purpose is when-does-this-close. Detection needs BOTH
#: the vocabulary and the absence of a sale window, because "öğrencilere özel
#: 3 gün %30" is a real, dated campaign that happens to target students.
EVERGREEN_TERMS: tuple[str, ...] = (
    "ogrenci", "ogrenciler", "ogrencilere", "student", "students", "youth",
    "kurumsal", "corporate", "sirketler icin", "business traveller",
    "senior", "65 yas", "65 yas ustu", "emekli", "retiree",
    "resident", "residents", "mukim", "ikamet", "diplomat",
    "her zaman", "her zaman gecerli", "yil boyu", "yil boyunca", "surekli",
    "always", "always available", "year round", "standing offer",
    "engelli", "gazi", "sehit yakini", "ogretmen", "teacher",
)
_EVERGREEN = _keyword_pattern(EVERGREEN_TERMS)

#: Something other than a seat is on sale. Baggage, lounges, seat selection,
#: hotels and car hire are ancillary revenue -- legitimate aviation news, and
#: never a fare campaign. The hotel half is imported from gate.py rather than
#: retyped: that list already knows about Bonvoy, Hyatt and "konaklama", and
#: two copies of it would drift on the first addition to either.
PRODUCT_TERMS: tuple[str, ...] = (
    "bagaj", "bagaj hakki", "ek bagaj", "baggage", "extra baggage", "luggage",
    "lounge", "lounge access", "bekleme salonu", "cip salonu",
    "koltuk secimi", "seat selection", "seat upgrade", "yer secimi",
    "arac kiralama", "car rental", "rent a car", "transfer hizmeti",
    "wifi", "yemek servisi", "inflight meal", "sigorta", "insurance",
    "esim", "otopark", "parking",
) + DISTRACTOR_TERMS["hotel"]
_PRODUCT = _keyword_pattern(PRODUCT_TERMS)

#: Miles, points and status. The single largest category among the 129 wrong
#: rows -- Avios bonus sales, Flying Blue devaluations, TrueBlue point
#: purchases -- all of which are about the currency, not about the fare.
LOYALTY_TERMS: tuple[str, ...] = (
    "mil", "mil kazan", "mil kazanim", "bonus mil", "mile", "miles",
    "puan", "puanlar", "bolpuan", "point", "points", "bonus points",
    "statu", "status match", "statu esitleme", "elite status", "tier",
    "miles smiles", "milesandsmiles", "avios", "skywards", "flying blue",
    "trueblue", "bolbol", "executive club", "frequent flyer", "mileage",
    "odul bilet", "award ticket", "award chart", "redemption",
    "sadakat programi", "loyalty programme", "loyalty program",
)
_LOYALTY = _keyword_pattern(LOYALTY_TERMS)

#: What a page that actually wants to sell you a ticket says. Its ABSENCE is
#: the signal -- together with no dates and no rate, it means the page reports
#: a campaign rather than being one. Deliberately loose: every term here makes
#: NEWS_ONLY *less* likely, so a false match costs nothing but a row that
#: survives to the next guard, while a missing term would reject a real
#: campaign.
BOOKING_CTA_TERMS: tuple[str, ...] = (
    "rezervasyon", "rezerve", "bilet al", "biletini al", "satin al",
    "hemen al", "hemen rezervasyon", "simdi al", "bilet satin",
    "book", "book now", "booking", "buy", "buy now", "purchase", "reserve",
    "get it now", "shop", "kesfet", "firsati kacirma", "son gun",
)
_BOOKING_CTA = _keyword_pattern(BOOKING_CTA_TERMS)


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


def _first_match(pattern, text: str) -> str | None:
    """The matched phrase, so the reason can quote what actually decided it."""
    found = pattern.search(text)
    return found.group(0) if found else None


def _business_class(
    text: str, campaign: CampaignExtraction
) -> tuple[str, str | None] | None:
    """The non-fare class this page belongs to, or None if it is a fare campaign.

    Order is by how specific the evidence is, not by how common the class is.
    A page saying both "bagaj" and "mil" is a product promo that happens to
    award miles, so PRODUCT is asked first; LOYALTY is next because its
    vocabulary is unambiguous; EVERGREEN needs a second condition and so comes
    after the two that do not; NEWS_ONLY is last because it is defined by
    absence and everything positive should get its say first.
    """
    product = _first_match(_PRODUCT, text)
    if product:
        return "PRODUCT_PROMOTION", product

    loyalty = _first_match(_LOYALTY, text)
    if loyalty:
        return "LOYALTY_PROMOTION", loyalty

    # Evergreen needs the vocabulary AND no sale window: a student fare that
    # runs for three days in September is a real campaign that happens to
    # target students, and rejecting it would be the rulepack overreaching.
    has_sale_window = campaign.sale_starts is not None or campaign.sale_ends is not None
    evergreen = _first_match(_EVERGREEN, text)
    if evergreen and not has_sale_window:
        return "EVERGREEN_OFFER", evergreen

    # Nothing to book, nothing to book it by, and nothing off the price: an
    # article about the campaign surface rather than a campaign.
    has_any_date = any(
        value is not None
        for value in (
            campaign.sale_starts,
            campaign.sale_ends,
            campaign.travel_starts,
            campaign.travel_ends,
        )
    )
    if not has_any_date and campaign.discount_pct is None and not _BOOKING_CTA.search(text):
        return "NEWS_ONLY", None

    return None


_CLASS_REASONS: dict[str, str] = {
    "PRODUCT_PROMOTION": (
        "Bagaj, lounge, otel gibi yan ürün/hizmet kampanyası — bilet ücreti kampanyası değil"
    ),
    "LOYALTY_PROMOTION": (
        "Mil/puan kazanımı veya sadakat programı kampanyası — ücret kampanyası değil"
    ),
    "EVERGREEN_OFFER": (
        "Belirli bir yolcu grubuna sürekli sunulan standart teklif, satış dönemi yok "
        "— süreli ücret kampanyası değil"
    ),
    "NEWS_ONLY": (
        "Tarih, indirim oranı ve rezervasyon çağrısı yok — kampanyayı anlatan içerik, "
        "kampanyanın kendisi değil"
    ),
}


def _rejection_reason(business_class: str, evidence: str | None) -> str:
    """One Turkish sentence, quoting the phrase that decided it where there is
    one. A verdict the analyst cannot check is a verdict they cannot trust."""
    base = _CLASS_REASONS[business_class]
    if evidence:
        return f"{base} (\"{evidence}\" geçiyor)."
    return f"{base}."


def _acceptance_reason(campaign: CampaignExtraction) -> str:
    """What this row was accepted on, in the reader's language."""
    stated: list[str] = []
    if campaign.sale_starts or campaign.sale_ends:
        stated.append(
            f"satış dönemi ({format_optional_range(campaign.sale_starts, campaign.sale_ends)})"
        )
    elif campaign.travel_starts or campaign.travel_ends:
        stated.append(
            "seyahat dönemi "
            f"({format_optional_range(campaign.travel_starts, campaign.travel_ends)})"
        )
    if campaign.discount_pct is not None:
        stated.append(f"%{campaign.discount_pct} indirim")

    if not stated:
        return (
            "Ücret kampanyası olarak sınıflandırıldı; tarih ve indirim oranı "
            "kaynakta belirtilmemiş."
        )
    return f"{' ve '.join(stated).capitalize()} açıkça belirtilmiş; ücret kampanyası."


def validate_campaign(
    title: str,
    campaign: CampaignExtraction,
    *,
    today: date | None = None,
    text: str | None = None,
) -> Outcome[CampaignExtraction]:
    """The second validation layer, on top of the model's own verdict.

    Downgrades a CLASSIFIED campaign to NOT_APPLICABLE when it matches one of
    the patterns still reaching production after the model-level fix. Never
    upgrades or invents -- this only ever narrows what the model already said
    yes to.

    `text` is the page or article body when the caller has one; the rulepacks
    read title and body together. It is optional because the golden-set
    evaluator (services/golden_eval_service.py) grades labelled titles with no
    body available, and a rulepack that needs a body would silently stop
    grading there.

    Both verdicts carry `business_class` and `classification_reason` in
    `details`. Callers that only read `.payload` and `.reason` -- which is all
    of them today -- are unaffected; PR4 writes both onto the row.

    Guard order is deliberate: the three date guards run first so their
    machine-readable reasons stay stable (they are what the golden-set
    regression asserts on), and because "this window is a partnership, not a
    sale" is a statement about the extraction rather than about the page. The
    date guards leave `business_class` null -- they are not business-class
    verdicts, and services/campaign_status.py owns the EXPIRED question.
    """
    reference = today or date.today()

    if _looks_expired(title):
        return Outcome.not_applicable(
            "expired_title",
            business_class=None,
            classification_reason=(
                "Başlık kampanyanın süresinin dolduğunu belirtiyor "
                "([Expired]/[Deal Alert]) — canlı kampanya olarak yayınlanmadı."
            ),
        )

    if _window_is_implausible(campaign.sale_starts, campaign.sale_ends):
        span = (campaign.sale_ends - campaign.sale_starts).days
        return Outcome.not_applicable(
            "implausible_sale_window",
            business_class=None,
            classification_reason=(
                f"Satış dönemi {span} gün "
                f"({format_optional_range(campaign.sale_starts, campaign.sale_ends)}) — "
                f"gerçek bir bilet kampanyası için fazla uzun "
                f"(üst sınır {MAX_SALE_WINDOW_DAYS} gün); duyuru ya da iş birliği."
            ),
        )

    if _window_is_stale(campaign.sale_ends, today=reference):
        return Outcome.not_applicable(
            "sale_window_closed",
            business_class=None,
            classification_reason=(
                f"Satış dönemi {campaign.sale_ends.isoformat()} tarihinde kapandı; "
                f"{STALE_AFTER_DAYS} günlük gösterim toleransı aşıldı."
            ),
        )

    detected = _business_class(fold_text(f"{title}\n{text or ''}"), campaign)
    if detected is not None:
        business_class, evidence = detected
        return Outcome.not_applicable(
            f"business_class:{business_class}",
            business_class=business_class,
            classification_reason=_rejection_reason(business_class, evidence),
        )

    return Outcome.classified(
        campaign,
        business_class="ACTIVE_CAMPAIGN",
        classification_reason=_acceptance_reason(campaign),
    )


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
