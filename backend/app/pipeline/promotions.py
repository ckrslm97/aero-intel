"""Turn campaign *articles* into structured `promotions` rows.

This is the reliable half of campaign detection. Direct scraping of airline
campaign pages (app/ingest/promo_scrape.py) only works for the one carrier
whose site serves real HTML; everything else in the competitive set is behind a
bot wall. But campaigns get *reported*, and the news pipeline already ingests,
translates, classifies and entity-links that reporting. So the backbone is:
take every article the pipeline filed under revenue_management > promotion (or
> pricing) that names one of the carriers we track, and pull the campaign's
window out of its prose.

Two extraction paths, same output shape:
  * the configured live model, prompted for strict JSON (see
    app/llm/prompts.py promotion_extraction_prompt);
  * a keyword/regex reader for Turkish campaign prose, used whenever no live
    model is configured -- which is the default locally and in any deployment
    without an LLM key. It is not as good, and it is not meant to be: it exists
    so the feature has no silent "returns nothing forever" mode.

Both paths obey the same rule, which is the whole design of this module: an
absent date stays absent. `promotions` has every date column nullable and the
timeline renders each missing field honestly (an open-ended bar fades out; a
campaign with no start date at all is a point, not a bar). A guessed date would
be drawn exactly like a published one, so guessing is the one unrecoverable
error here.

Idempotent by article URL -- re-running refreshes a row in place. And
idempotent by *campaign*, not just by URL: the same campaign reported by an
outlet and published on the airline's own page arrives here under two
different URLs, so every insert is matched against what is already on the
timeline first (app/pipeline/promo_dedup.py) and merged into it when it is
the same campaign wearing a different link.
"""
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.promotion import Promotion
from app.pipeline.promo_dedup import PromoCandidate, find_duplicate, merge_candidate
from app.taxonomy import TRACKED_AIRLINES as _TRACKED_AIRLINES

logger = get_logger(__name__)

# The competitive set the whole product is scoped to. Defined in app/taxonomy.py
# and re-exported here, where the pipeline reads it: the frontend's copy is
# generated from the same constant (taxonomy.gen.ts -> nav.ts `airlineTabs`,
# which is where each carrier's brand hex and logo come from), so the two sides
# can no longer disagree about which carriers exist. A campaign by a carrier
# outside this set has no lane to draw itself in, so it is left as the article
# it already is.
TRACKED_AIRLINES = _TRACKED_AIRLINES

# app/taxonomy.py revenue_management subcategories. "pricing" is in because a
# fare move announced as a price change rather than as a branded campaign is
# the same intelligence wearing a different word.
PROMO_SUBCATEGORIES = ("promotion", "pricing")

TR_MONTHS = (
    "ocak", "şubat", "mart", "nisan", "mayıs", "haziran",
    "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık",
)
_MONTH_INDEX = {name: i + 1 for i, name in enumerate(TR_MONTHS)}

# The English half. Airline campaign pages are bilingual far more often than
# the news feed is -- TK, QR, EK and BA publish the same campaign in English
# and Turkish, and the English page is frequently the one that is fetchable --
# so an English-only date was a campaign silently reduced to a dateless point
# marker. Abbreviations are in because marketing copy uses them freely
# ("Book by 28 Aug"), and "sept" is in because it is common enough that
# leaving it out would look like an oversight rather than a decision.
EN_MONTHS: tuple[str, ...] = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
EN_MONTH_ABBREVIATIONS: tuple[str, ...] = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)
_EN_MONTH_INDEX: dict[str, int] = {name: i + 1 for i, name in enumerate(EN_MONTHS)}
_EN_MONTH_INDEX.update({name: i + 1 for i, name in enumerate(EN_MONTH_ABBREVIATIONS)})
_EN_MONTH_INDEX["sept"] = 9
# Longest first: an unordered alternation lets "aug" win inside "august" and
# leaves a stray "ust" behind, which then fails to parse as anything.
_EN_MONTH_NAMES = "|".join(sorted(_EN_MONTH_INDEX, key=len, reverse=True))

# "15 Ekim 2026", "2 Mayıs", "31 Aralık'a" -- the apostrophe-suffix form is
# how Turkish attaches case endings to a date and is extremely common in
# campaign copy ("30 Kasım'a kadar").
_TR_DATE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(TR_MONTHS) + r")\b\s*(?:['’][a-zçğıöşü]+)?\s*(\d{4})?",
    re.IGNORECASE,
)
# "28 August 2026", "28 Aug", "1st September 2027" -- the British order, which
# is what the Gulf and Turkish carriers write.
_EN_DATE_DMY = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _EN_MONTH_NAMES + r")\b\.?,?\s*(\d{4})?",
    re.IGNORECASE,
)
# "Aug 28, 2026", "August 28" -- the American order. Both are read, because
# both appear on the same pages; unlike the numeric form below there is no
# ambiguity between them, since the month is spelled out.
_EN_DATE_MDY = re.compile(
    r"\b(" + _EN_MONTH_NAMES + r")\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b,?\s*(\d{4})?",
    re.IGNORECASE,
)
# 02.05.2026 / 02/05/2026 -- read as DD/MM, the Turkish convention.
#
# This is knowingly ambiguous: "02/05/2026" is 2 May to every source this
# product reads and 5 February to a US one. The resolution is deliberate
# rather than accidental. Every carrier in TRACKED_AIRLINES writes DD/MM on
# its own pages (Turkish, European and Gulf convention alike), the news feed
# is predominantly Turkish, and there is no signal in a bare numeric date to
# disambiguate on -- so a "smart" heuristic would only be a coin flip wearing
# a comment. Where a US-format date matters, the spelled-out month forms above
# read it correctly; this pattern stays DD/MM.
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

# "%40", "%40'a varan", "40%". Two digits max: "%100" is real but a three-digit
# match is almost always a price or a flight number picking up a stray %.
_PCT = re.compile(r"%\s*(\d{1,3})|(\d{1,3})\s*%")

# Which window a date range belongs to, read from the words just before it.
# Turkish campaign copy is consistent about this: a sale window is introduced
# by satış/alım/rezervasyon/bilet, a travel window by seyahat/uçuş/gidiş.
_SALE_CUES = (
    "satış", "satis", "satın", "satin", "alım", "alim", "rezervasyon",
    "bilet al", "bilet satış", "geçerlilik", "gecerlilik", "kampanya",
    "son gün", "booking", "book by", "sale",
    # English, matched as substrings like the Turkish ones above: "book"
    # subsumes "book by"/"booking" and costs nothing to state, "valid" is how
    # an offer's own window is introduced ("valid until"), and the rest are
    # the verbs a booking deadline is written with.
    "book", "reserve", "purchase", "buy", "valid", "on sale",
)
_TRAVEL_CUES = (
    "seyahat", "uçuş", "ucus", "uçacak", "gidiş", "gidis", "dönüş", "donus",
    "kalkış", "travel", "fly", "flight", "depart", "journey",
)
# How far back from a range we look for one of those cues.
_CUE_WINDOW = 90

# A deadline or a start can be announced either side of the date, and which
# side depends on the language: Turkish puts it after ("30 Kasım'a kadar"),
# English puts it before ("Book until 31 December"). The tail patterns are the
# original ones; the head patterns are anchored to the end of the preceding
# text so the cue has to be the word immediately before the date -- without
# that anchor "announced by Turkish Airlines on 5 January" reads as a booking
# deadline of 5 January, which is not what it says.
_DEADLINE_TAIL = re.compile(r"kadar|son(?:una)?\b|until|through|by\b")
_DEADLINE_HEAD = re.compile(
    r"\b(?:until|through|thru|by|before|no later than|not later than"
    r"|ends?(?: on)?|last day(?: is)?|deadline(?: is)?|en geç|en gec|son tarih)"
    r"\s*:?\s*$"
)
_START_TAIL = re.compile(r"itibaren|başlıyor|basliyor|from\b|starting")
_START_HEAD = re.compile(
    r"\b(?:from|starting(?: on)?|starts?(?: on)?|beginning(?: on)?"
    r"|as of|effective(?: from)?|valid from)\s*:?\s*$"
)
# How far before a date we look for one of those edge cues. Deliberately much
# shorter than _CUE_WINDOW: "which window is this" is a paragraph-level
# question, "is this an end date" is a two-word one.
_EDGE_CUE_WINDOW = 26

# What can sit between two dates and still leave them one range. "and" and
# "through" are the English forms of "ile"/"arası" and are what makes
# "travel between 1 October and 31 December" a window rather than two
# unrelated dates.
_RANGE_SEPARATOR = re.compile(
    r"[-–—/]|\bile\b|\barası|\bve\b|\bto\b|\band\b|\bthrough\b|\bthru\b|\buntil\b"
)

# Turkish market names -> world-region slug (app/taxonomy.py COUNTRY_TO_REGION
# values). Cities are kept as written; the drawer maps slugs through
# nav.ts worldRegions and renders anything else as-is.
_MARKET_REGIONS: dict[str, str] = {
    "avrupa": "europe",
    "orta doğu": "middle-east",
    "ortadoğu": "middle-east",
    "afrika": "africa",
    "kuzey amerika": "north-america",
    "güney amerika": "south-america",
    "orta amerika": "central-america",
    "uzak doğu": "asia",
    "asya": "asia",
    "güneydoğu asya": "southeast-asia",
    "okyanusya": "oceania",
}
_MARKET_CITIES = (
    "istanbul", "ankara", "izmir", "antalya", "londra", "paris", "berlin",
    "amsterdam", "roma", "milano", "madrid", "barselona", "viyana", "münih",
    "dubai", "doha", "abu dabi", "new york", "bakü", "tiflis", "atina",
    "kıbrıs", "kuzey kıbrıs", "saraybosna", "tiran", "belgrad", "budapeşte",
)
_MAX_MARKETS = 6


@dataclass
class PromotionFields:
    """What either extraction path produces. Every field is optional because
    every field is genuinely optional in the source material."""

    discount_pct: int | None = None
    sale_starts: date | None = None
    sale_ends: date | None = None
    travel_starts: date | None = None
    travel_ends: date | None = None
    markets: str | None = None


def _fold(text: str) -> str:
    """Lowercase for matching. Turkish 'İ'.lower() grows a combining dot that
    no literal in this file contains, so it is stripped."""
    return unicodedata.normalize("NFC", text.lower()).replace("̇", "")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates_flagged(
    text: str, default_year: int | None = None
) -> list[tuple[int, date, bool]]:
    """Every date in `text`, as (character offset, date, year_was_inferred).

    The third element is the one `find_dates` cannot carry. "15 Ekim" and
    "15 Ekim 2026" produce the same `date` object, but only one of them was
    actually stated: the other was completed from `default_year`, the
    article's own publication year, which is the least-wrong reading available
    and still a reading rather than a quote. A campaign published in December
    and advertising "10 Ocak" means next January, and this flag is what lets
    the caller record that doubt (`promotions.date_flags_json`) and the drawer
    show it, instead of drawing an inferred date exactly like a published one.

    `default_year` fills in a yearless date; with no default_year a yearless
    date is dropped rather than assigned an arbitrary one -- unchanged
    behaviour, and the reason this stays a flag rather than a rejection.

    Four patterns feed this, in precedence order: Turkish, English D-M-Y,
    English M-D-Y, numeric. Overlapping matches are suppressed so one date can
    never be counted twice -- with four patterns over the same string that is
    no longer only theoretical, and a double-counted date would let the range
    pairing below build a window out of one date and itself.
    """
    folded = _fold(text)
    spans: list[tuple[int, int, date, bool]] = []

    def claim(match: re.Match[str], parsed: date | None, inferred: bool) -> None:
        if parsed is None:
            return
        start, end = match.span()
        if any(start < taken_end and taken_start < end for taken_start, taken_end, _, _ in spans):
            return
        spans.append((start, end, parsed, inferred))

    def resolve_year(raw: str | None) -> tuple[int | None, bool]:
        if raw:
            return int(raw), False
        return default_year, True

    for match in _TR_DATE.finditer(folded):
        year, inferred = resolve_year(match.group(3))
        if year is None:
            continue
        claim(match, _safe_date(year, _MONTH_INDEX[match.group(2)], int(match.group(1))), inferred)

    for match in _EN_DATE_DMY.finditer(folded):
        year, inferred = resolve_year(match.group(3))
        if year is None:
            continue
        month = _EN_MONTH_INDEX[match.group(2)]
        claim(match, _safe_date(year, month, int(match.group(1))), inferred)

    for match in _EN_DATE_MDY.finditer(folded):
        year, inferred = resolve_year(match.group(3))
        if year is None:
            continue
        month = _EN_MONTH_INDEX[match.group(1)]
        claim(match, _safe_date(year, month, int(match.group(2))), inferred)

    for match in _NUMERIC_DATE.finditer(folded):
        claim(
            match,
            _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1))),
            False,
        )

    spans.sort(key=lambda item: item[0])
    return [(start, parsed, inferred) for start, _, parsed, inferred in spans]


def find_dates(text: str, default_year: int | None = None) -> list[tuple[int, date]]:
    """Every date in `text`, as (character offset, date), in document order.

    The original two-tuple shape, kept because every current caller wants
    exactly this and none of them can act on the inferred-year flag yet. It
    delegates rather than duplicating the parsing, so the two views of the
    same text can never disagree about what a date is.
    """
    return [(offset, parsed) for offset, parsed, _ in find_dates_flagged(text, default_year)]


def _classify_window(text: str, offset: int) -> str:
    """'sale' or 'travel', from the nearest cue word before `offset`."""
    window = text[max(0, offset - _CUE_WINDOW) : offset]
    sale_at = max((window.rfind(cue) for cue in _SALE_CUES), default=-1)
    travel_at = max((window.rfind(cue) for cue in _TRAVEL_CUES), default=-1)
    if travel_at > sale_at:
        return "travel"
    return "sale"


def _extract_markets(text: str) -> str | None:
    folded = _fold(text)
    hits: list[str] = []
    for name, slug in _MARKET_REGIONS.items():
        if name in folded and slug not in hits:
            hits.append(slug)
    # Longest first, then drop any match contained in one already taken:
    # "Kuzey Kıbrıs" and "Kıbrıs" both fire on the same words, and listing both
    # as separate markets would read as two destinations.
    matched = [city for city in sorted(_MARKET_CITIES, key=len, reverse=True) if city in folded]
    for city in matched:
        if not any(city != other and city in other for other in matched if other in hits):
            if city not in hits:
                hits.append(city)
    if not hits:
        return None
    return ",".join(hits[:_MAX_MARKETS])


def heuristic_extract(
    title: str, content: str, default_year: int | None = None
) -> PromotionFields:
    """Read a campaign's window out of Turkish (or English) prose with regexes.

    The fallback path, for deployments with no LLM configured. Deliberately
    conservative: it fills a field only when the text states it outright, and
    leaves everything else null for the UI to render as "belirtilmedi".
    """
    text = f"{title}\n{content}"
    folded = _fold(text)
    fields = PromotionFields()

    pct_match = _PCT.search(folded)
    if pct_match:
        raw = pct_match.group(1) or pct_match.group(2)
        value = int(raw)
        # 0 is not a discount and >100 is a misparse (a price, a flight number).
        if 0 < value <= 100:
            fields.discount_pct = value

    dates = find_dates(text, default_year)
    # Pair consecutive dates into ranges when they read as one ("15 Ekim - 30
    # Kasım", "02 Mayıs 2026 / 30 Kasım 2026"): adjacent in the text, in order,
    # and with nothing but a separator between them.
    used: set[int] = set()
    for i in range(len(dates) - 1):
        if i in used:
            continue
        start_at, start_date = dates[i]
        end_at, end_date = dates[i + 1]
        between = folded[start_at:end_at]
        # Long enough to hold a separator and a date, not a whole sentence.
        if len(between) > 60 or end_date < start_date:
            continue
        if not _RANGE_SEPARATOR.search(between):
            continue
        kind = _classify_window(folded, start_at)
        # Both ends must belong to the same window, or this is not one range.
        # "Book until 31 December 2026 for travel until 31 March 2027" has two
        # dates, a separator between them and only sixteen characters in
        # between -- and pairing them produces a fifteen-month "booking
        # window" assembled from a booking deadline and a travel deadline.
        # Conflating those two is the specific failure the whole
        # sale/travel column split exists to prevent, so a disagreement about
        # which window a date belongs to blocks the pairing rather than being
        # resolved in favour of whichever date came first.
        if kind != _classify_window(folded, end_at):
            continue
        if kind == "travel" and fields.travel_starts is None:
            fields.travel_starts, fields.travel_ends = start_date, end_date
            used |= {i, i + 1}
        elif kind == "sale" and fields.sale_starts is None:
            fields.sale_starts, fields.sale_ends = start_date, end_date
            used |= {i, i + 1}

    # A lone date after "…e kadar" / before "until …" is an END, not a start.
    # This is the single most common shape in campaign copy ("30 Kasım'a
    # kadar", "Book by 31 December") and reading it as a start would draw the
    # bar in the wrong place entirely. Turkish states the cue after the date,
    # English before it, so both sides are read.
    for i, (offset, value) in enumerate(dates):
        if i in used:
            continue
        tail = folded[offset : offset + 60]
        head = folded[max(0, offset - _EDGE_CUE_WINDOW) : offset]
        is_deadline = bool(_DEADLINE_TAIL.search(tail)) or bool(_DEADLINE_HEAD.search(head))
        kind = _classify_window(folded, offset)
        if is_deadline:
            if kind == "travel" and fields.travel_ends is None:
                fields.travel_ends = value
                used.add(i)
            elif kind == "sale" and fields.sale_ends is None:
                fields.sale_ends = value
                used.add(i)
        elif _START_TAIL.search(tail) or _START_HEAD.search(head):
            if kind == "travel" and fields.travel_starts is None:
                fields.travel_starts = value
                used.add(i)
            elif kind == "sale" and fields.sale_starts is None:
                fields.sale_starts = value
                used.add(i)

    fields.markets = _extract_markets(text)
    return fields


def _parse_iso(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_llm_payload(raw: str) -> PromotionFields | None:
    """Read the model's JSON. Returns None when it isn't usable, so the caller
    falls through to the heuristic rather than writing an empty row."""
    if not raw:
        return None
    text = raw.strip()
    # Small models fence their JSON despite being told not to.
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    pct = payload.get("discount_pct")
    if isinstance(pct, str) and pct.strip().rstrip("%").isdigit():
        pct = int(pct.strip().rstrip("%"))
    if not isinstance(pct, int) or isinstance(pct, bool) or not 0 < pct <= 100:
        pct = None

    markets = payload.get("markets")
    if isinstance(markets, list):
        markets = ",".join(str(m).strip() for m in markets if str(m).strip())
    if not isinstance(markets, str) or not markets.strip():
        markets = None
    else:
        markets = markets.strip()[:500]

    return PromotionFields(
        discount_pct=pct,
        sale_starts=_parse_iso(payload.get("sale_starts")),
        sale_ends=_parse_iso(payload.get("sale_ends")),
        travel_starts=_parse_iso(payload.get("travel_starts")),
        travel_ends=_parse_iso(payload.get("travel_ends")),
        markets=markets,
    )


def _coherent(fields: PromotionFields) -> PromotionFields:
    """Drop a range that runs backwards rather than drawing a negative bar."""
    if fields.sale_starts and fields.sale_ends and fields.sale_ends < fields.sale_starts:
        fields.sale_ends = None
    if fields.travel_starts and fields.travel_ends and fields.travel_ends < fields.travel_starts:
        fields.travel_ends = None
    return fields


async def _candidate_articles(db: AsyncSession, limit: int | None) -> list[Article]:
    """Campaign articles that name a carrier we track.

    Duplicates are excluded: the same campaign filed by three outlets should be
    one bar on the timeline, and dedup has already picked the canonical row.
    """
    query = (
        select(Article)
        .options(selectinload(Article.source), selectinload(Article.enrichment))
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            ArticleEnrichment.category == "revenue_management",
            ArticleEnrichment.subcategory.in_(PROMO_SUBCATEGORIES),
            Article.is_duplicate.is_(False),
            select(ArticleEntity.article_id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(
                ArticleEntity.article_id == Article.id,
                Entity.entity_type == "airline",
                Entity.code.in_(tuple(TRACKED_AIRLINES)),
            )
            .exists(),
        )
        .order_by(Article.published_at.desc().nulls_last())
    )
    if limit is not None:
        query = query.limit(limit)
    return list((await db.execute(query)).scalars().all())


async def _primary_airline(db: AsyncSession, article_id) -> tuple[str, str] | None:
    """The tracked carrier this article is most about."""
    rows = (
        await db.execute(
            select(Entity.code, ArticleEntity.relevance)
            .join(ArticleEntity, ArticleEntity.entity_id == Entity.id)
            .where(
                ArticleEntity.article_id == article_id,
                Entity.entity_type == "airline",
                Entity.code.in_(tuple(TRACKED_AIRLINES)),
            )
            .order_by(ArticleEntity.relevance.desc())
        )
    ).all()
    if not rows:
        return None
    code = rows[0][0]
    return code, TRACKED_AIRLINES[code]


async def extract_promotions(
    db: AsyncSession, limit: int | None = None, use_llm: bool = True
) -> dict[str, int]:
    """Walk campaign articles and upsert a `promotions` row for each.

    Returns counts rather than a bare number: "12 scanned, 3 new, 9 refreshed,
    2 merged" is the shape that tells you whether a run did anything, and the
    scheduled job logs it every 45 minutes.
    """
    from app.llm.factory import get_raw_generator

    generate = get_raw_generator() if use_llm else None
    articles = await _candidate_articles(db, limit)
    stats = {
        "scanned": len(articles),
        "inserted": 0,
        "updated": 0,
        "merged": 0,
        "skipped": 0,
        "llm": 0,
    }

    for article in articles:
        airline = await _primary_airline(db, article.id)
        if airline is None:
            stats["skipped"] += 1
            continue
        code, name = airline

        enrichment = article.enrichment
        title = (enrichment.headline_tr or enrichment.headline or article.title) if enrichment else article.title
        summary = (enrichment.summary_tr or enrichment.summary or "") if enrichment else ""
        body = f"{summary}\n{article.raw_content or ''}".strip()

        fields: PromotionFields | None = None
        if generate is not None:
            from app.llm.prompts import promotion_extraction_prompt

            try:
                raw = await generate(promotion_extraction_prompt(title, body))
                fields = parse_llm_payload(raw)
                if fields is not None:
                    stats["llm"] += 1
            except Exception as exc:  # noqa: BLE001 -- one bad article must not end the run
                logger.warning("promotion_llm_extract_failed", url=article.url, error=str(exc))
        if fields is None:
            published_year = article.published_at.year if article.published_at else None
            fields = heuristic_extract(title, body, default_year=published_year)
        fields = _coherent(fields)

        detected = article.published_at or article.fetched_at or datetime.now(timezone.utc)
        candidate = PromoCandidate(
            airline_code=code,
            airline_name=name,
            title_tr=title[:300],
            summary_tr=summary,
            url=article.url[:500],
            source_name=(article.source.name if article.source else "Haber"),
            detected_at=detected,
            discount_pct=fields.discount_pct,
            markets=fields.markets,
            sale_starts=fields.sale_starts,
            sale_ends=fields.sale_ends,
            travel_starts=fields.travel_starts,
            travel_ends=fields.travel_ends,
            region=enrichment.region if enrichment else None,
        )
        existing = (
            await db.execute(select(Promotion).where(Promotion.url == article.url))
        ).scalar_one_or_none()

        if existing is None:
            # No row under this article's URL does not mean no row: the airline
            # scraper (app/ingest/promo_scrape.py) files the same campaign under
            # the campaign page's URL, and a curated seed under a third. Merge
            # into whichever already exists rather than adding a second bar for
            # one campaign -- see app/pipeline/promo_dedup.py.
            twin = await find_duplicate(db, candidate)
            if twin is not None:
                # The diff `merge_candidate` returns is deliberately dropped
                # here, and on the refresh below. This extractor re-reads the
                # same article text every 30 minutes with an LLM whose answer
                # is not stable to the field, so a version row from this path
                # would record model variance, not a carrier moving its
                # campaign -- audit noise in the one table that has to stay
                # readable. The article-derived campaigns that ARE versioned
                # are the v2 ones agents/runner.py writes, where the reading is
                # taken once per cluster and merged against a source tier.
                merge_candidate(twin, candidate)
                await db.flush()
                stats["merged"] += 1
                continue
            db.add(
                Promotion(
                    airline_code=code,
                    airline_name=name,
                    title_tr=title[:300],
                    summary_tr=summary,
                    discount_pct=fields.discount_pct,
                    markets=fields.markets,
                    sale_starts=fields.sale_starts,
                    sale_ends=fields.sale_ends,
                    travel_starts=fields.travel_starts,
                    travel_ends=fields.travel_ends,
                    url=article.url[:500],
                    source_name=(article.source.name if article.source else "Haber"),
                    region=enrichment.region if enrichment else None,
                    # The article's own timestamp, not now(): backfilling five
                    # months of archive must not light up the "Yeni" banner
                    # with five months of campaigns at once.
                    detected_at=detected,
                )
            )
            await db.flush()
            stats["inserted"] += 1
        else:
            # A re-read of the same URL: this extraction is the newer reading,
            # so it wins every field it states -- but it does NOT get to null
            # out fields it no longer sees. The curated seed and this path share
            # URLs (app/ingest/promos_seed.py writes both the article and the
            # promotion row), and a re-run used to wipe the seed's verified sale
            # window with the extractor's blank, turning a dated bar into a
            # dateless point marker.
            merge_candidate(existing, candidate, prefer_candidate=True)
            stats["updated"] += 1

    await db.commit()
    logger.info("promotions_extracted", **stats)
    return stats
