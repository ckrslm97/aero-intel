"""Scheduled refresh of Turkish Airlines passenger reviews for the BİZ page.

Complements the hand-curated app/ingest/tk_reviews_seed.py: that module is a
frozen snapshot, this one goes out and fetches whatever is new. Both write to
the same table and share the same idempotency key (sha256 of url + excerpt), so
running either one twice is a no-op.

Sources actually used (all verified live before this module was written):
- Apple App Store customer-review RSS (JSON), storefronts us/gb/de/tr:
  https://itunes.apple.com/<cc>/rss/customerreviews/id=1283414961/sortby=mostrecent/json
  50 entries per storefront, star rating x2 -> the table's /10 scale.
- Skytrax (airlinequality.com) review listing, pages 1-2. Plain HTML with
  schema.org microdata (<article itemprop="review">); needs a browser
  User-Agent. ~10 dated, /10-scored reviews per page.
- Reddit r/TurkishAirlines top-of-month .rss (no API key). 25 entries, no
  scores -- sentiment comes from the heuristic lexicon instead.

Deliberately not used:
- TripAdvisor: bot protection (Cloudflare interstitial on every request),
  not worth the fragility.
- Google Play reviews: no keyless public endpoint; the unofficial scrapers
  break constantly.

Editorial rules baked in here:
- Excerpts are clipped to at most two sentences / 280 characters. This is
  quotation with attribution, not reproduction.
- excerpt_tr is left NULL on purpose: no LLM is called from this path (the
  Groq quota is spoken for by the news pipeline) and the BİZ page already
  falls back to `excerpt_tr or excerpt`. Translation is a separate pass.
- Every source runs inside its own try/except: a dead site or a markup change
  costs us that source for the run, never the whole run.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.heuristic import HeuristicProvider
from app.models.tk_review import TkReview

logger = get_logger(__name__)

APPSTORE_APP_ID = "1283414961"
APPSTORE_STOREFRONTS = ("us", "gb", "de", "tr")
APPSTORE_RSS = (
    "https://itunes.apple.com/{cc}/rss/customerreviews/"
    "id=" + APPSTORE_APP_ID + "/sortby=mostrecent/json"
)
# Canonical page we link to per storefront (matches the seed module's URLs so a
# live re-fetch of an already-curated review lands on the same dedupe key).
APPSTORE_PAGE = "https://apps.apple.com/{cc}/app/turkish-airlines-book-flights/id" + APPSTORE_APP_ID

SKYTRAX_BASE = "https://www.airlinequality.com/airline-reviews/turkish-airlines/"
SKYTRAX_PAGES = (SKYTRAX_BASE, f"{SKYTRAX_BASE}page/2/")

REDDIT_RSS = "https://www.reddit.com/r/TurkishAirlines/top/.rss?t=month"

SOURCE_APPSTORE = "App Store"
SOURCE_SKYTRAX = "Skytrax"
SOURCE_REDDIT = "Reddit r/TurkishAirlines"

# itunes.apple.com and reddit.com both 429/403 a default httpx UA; Skytrax
# returns an empty shell without a browser UA.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = httpx.Timeout(20.0)

MAX_EXCERPT_CHARS = 280
MAX_EXCERPT_SENTENCES = 2
# App-store feeds are full of "10", "👍" and "Good" entries. They carry no
# opinion worth quoting on the page, and they are short enough to collide with
# the near-duplicate guard, so they never make it past parsing.
MIN_EXCERPT_CHARS = 25
MAX_THEMES = 3

# Column widths in app.models.tk_review -- clip rather than blow up on insert.
_MAX_AUTHOR = 120
_MAX_ROUTE = 60

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")

# Keyword -> REVIEW_THEMES slug. Matched as whole words on the lower-cased
# excerpt, so "bag" does not fire on "bagel" and "ist" does not fire on "exist".
_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cabin_crew": (
        "crew", "attendant", "attendants", "stewardess", "hostess", "staff",
        "cabin service", "purser",
    ),
    "delay": (
        "delay", "delayed", "delays", "late", "cancel", "cancelled", "canceled",
        "cancellation", "cancellations", "diverted", "missed connection",
    ),
    "baggage": ("bag", "bags", "baggage", "luggage", "suitcase", "checked bag"),
    "food": (
        "food", "meal", "meals", "catering", "breakfast", "dinner", "snack",
        "snacks", "drinks",
    ),
    "seat_comfort": (
        "seat", "seats", "seating", "legroom", "leg room", "recline", "cramped",
        "lie-flat", "comfort", "comfortable",
    ),
    "ist_transfer": (
        "istanbul", "transit", "transfer", "connection", "connecting", "layover",
        "stopover", "iga",
    ),
    "miles_smiles": (
        "miles", "smiles", "loyalty", "frequent flyer", "elite", "award ticket",
        "reward flight", "reward flights",
    ),
    "refund_service": (
        "refund", "refunded", "customer service", "complaint", "complaints",
        "compensation", "reimburse", "reimbursement", "call center", "call centre",
    ),
    "value": (
        "price", "prices", "pricing", "value", "expensive", "cheap", "fare",
        "fares", "cost", "overpriced",
    ),
    "entertainment": (
        "wifi", "wi-fi", "screen", "screens", "entertainment", "infotainment",
        "ife", "movies", "usb",
    ),
}

_THEME_PATTERNS: dict[str, re.Pattern[str]] = {
    slug: re.compile("|".join(rf"\b{re.escape(kw)}\b" for kw in keywords))
    for slug, keywords in _THEME_KEYWORDS.items()
}


@dataclass(frozen=True)
class LiveReview:
    """One fetched review, already normalized to the TkReview column shapes."""

    source_name: str
    url: str
    excerpt: str
    review_date: date | None = None
    rating: float | None = None  # normalized /10
    author: str | None = None
    route: str | None = None
    # The pre-normalization score ("4/5 App Store (GB)"). tk_reviews has no
    # column for it, so it stays in-process for logs/debugging rather than
    # forcing a migration onto a table other agents own.
    rating_note: str | None = None
    extra: dict = field(default_factory=dict)


def clip_excerpt(text: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """Keep at most two sentences and `max_chars` characters.

    Copyright hygiene: we quote, we do not republish. Whole sentences are kept
    where possible; a single sentence longer than the budget is cut at a word
    boundary with an ellipsis so it never ends mid-word.
    """
    cleaned = _WHITESPACE_RE.sub(" ", (text or "")).strip()
    if not cleaned:
        return ""

    sentences = [s for s in _SENTENCE_SPLIT_RE.split(cleaned) if s]
    kept: list[str] = []
    for sentence in sentences[:MAX_EXCERPT_SENTENCES]:
        candidate = " ".join([*kept, sentence])
        if kept and len(candidate) > max_chars:
            break
        kept.append(sentence)
        if len(" ".join(kept)) >= max_chars:
            break

    result = " ".join(kept).strip()
    if len(result) <= max_chars:
        return result

    # First sentence alone overshoots -- cut at the last word boundary that fits.
    head = result[: max_chars - 1]
    if " " in head:
        head = head[: head.rindex(" ")]
    return head.rstrip(" ,;:-") + "…"


async def sentiment_for(rating: float | None, text: str) -> str:
    """Score-driven when the source gives one, lexicon-driven otherwise.

    A star rating is a far better signal than a word list, so it wins whenever
    the source publishes one; only score-less sources (Reddit) fall through to
    the keyless heuristic provider.
    """
    if rating is not None:
        if rating >= 7:
            return "positive"
        if rating <= 4:
            return "negative"
        return "neutral"
    return await HeuristicProvider().sentiment("", text)


def tag_themes(text: str) -> list[str]:
    """Map an excerpt onto at most three REVIEW_THEMES slugs, strongest first."""
    lowered = (text or "").lower()
    scored: list[tuple[int, str]] = []
    for slug, pattern in _THEME_PATTERNS.items():
        hits = len(pattern.findall(lowered))
        if hits:
            scored.append((hits, slug))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [slug for _, slug in scored[:MAX_THEMES]]


def dedupe_key(url: str, excerpt: str) -> str:
    """Same recipe as the seed module: sha256(url + '|' + excerpt)."""
    return hashlib.sha256(f"{url}|{excerpt}".encode()).hexdigest()


def _squash(excerpt: str) -> str:
    """Punctuation- and case-free form of an excerpt, for overlap comparison.

    Unicode-aware on purpose: the TR/DE storefronts and Reddit carry Turkish,
    Russian and Arabic reviews, and an ASCII-only filter would flatten all of
    them to the empty string -- which would then look like one big duplicate.
    """
    return re.sub(r"[\W_]+", "", (excerpt or "").lower(), flags=re.UNICODE)


# How many squashed characters have to line up before two excerpts are treated
# as the same review. 60 is roughly one sentence: long enough that unrelated
# reviews never collide, short enough to survive a different clip point.
_OVERLAP_WINDOW = 60


# The BİZ page is about flying Turkish Airlines, not about their mobile app.
# The app stores are full of "can't paste my password into the login screen"
# reviews; the curated seed skipped those by hand and so does this pass. A
# review is dropped only when it talks about the software *and* never mentions
# the journey -- "the app is clunky but the crew were lovely" stays.
_APP_ONLY_RE = re.compile(
    r"\b(app|apps|application|website|site|web|login|log in|sign in|password|"
    r"update|updates|bug|bugs|crash|crashes|glitch|interface|ui|ux|uygulama)\b",
    re.IGNORECASE,
)
_FLIGHT_RE = re.compile(
    r"\b(flight|flights|flew|fly|flying|flown|crew|cabin|onboard|on board|board|"
    r"boarding|seat|seats|meal|meals|food|catering|luggage|baggage|lounge|airport|"
    r"aircraft|plane|pilot|attendant|attendants|legroom|transit|layover|stopover|"
    r"business class|economy|uçuş|uçak|kabin|koltuk)\b",
    re.IGNORECASE,
)


def is_quotable(excerpt: str) -> bool:
    """Filter out what does not belong on a passenger-experience page.

    Two rules, both learned from the curated corpus: an excerpt has to be long
    enough to carry an opinion (the feeds are full of "10" and "👍"), and it
    must not be a pure app-store software complaint. Note that neither rule
    requires English -- theme keywords are English-only, so anything stricter
    would quietly throw away the Turkish and German storefronts.
    """
    if len(_squash(excerpt)) < MIN_EXCERPT_CHARS:
        return False
    if _CHATBOT_TELL_RE.search(excerpt):
        return False
    if _APP_ONLY_RE.search(excerpt) and not _FLIGHT_RE.search(excerpt):
        return False
    return True


# Reviews that were pasted straight out of a chatbot, prompt and all. The
# curator hit one of these by hand in the App Store feed ("Okay, here's a draft
# in your voice..."); quoting them as passenger opinion would be a lie.
_CHATBOT_TELL_RE = re.compile(
    r"\b(here'?s a draft|in your voice|as an ai|as an? language model|"
    r"sure,? here'?s|rewrite this review)\b",
    re.IGNORECASE,
)


def is_near_duplicate(excerpt: str, known: list[str]) -> bool:
    """True when `excerpt` is substantially the same text as something we hold.

    The strict dedupe_key only catches byte-identical (url, excerpt) pairs, and
    the same review legitimately reaches us in different shapes: the curated
    seed clipped it at a different sentence, or stored it under the bare
    listing URL while the live pass anchors it. Checking whether either text's
    first sentence-worth of characters occurs inside the other catches both,
    without the cost of real fuzzy matching.
    """
    candidate = _squash(excerpt)
    if not candidate:
        return True
    head = candidate[:_OVERLAP_WINDOW]
    for other in known:
        if not other:
            continue
        if head in other or other[:_OVERLAP_WINDOW] in candidate:
            return True
    return False


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = _WHITESPACE_RE.sub(" ", value).strip()
    if not value:
        return None
    return value[:limit]


def _to_float(value: str | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Apple App Store customer-review RSS (JSON)
# --------------------------------------------------------------------------

def _label(node: object) -> str:
    """iTunes wraps every scalar as {"label": "..."} -- unwrap defensively."""
    if isinstance(node, dict):
        value = node.get("label")
        return value.strip() if isinstance(value, str) else ""
    if isinstance(node, str):
        return node.strip()
    return ""


def parse_appstore(payload: dict, storefront: str) -> list[LiveReview]:
    """feed.entry[] -> LiveReview, converting the 1-5 stars to the /10 scale.

    Entries without a star rating are the feed's own app-metadata rows (and the
    occasional malformed entry), so they are skipped rather than stored as
    score-less reviews.
    """
    feed = (payload or {}).get("feed") or {}
    entries = feed.get("entry") or []
    if isinstance(entries, dict):  # single-review storefronts come back unwrapped
        entries = [entries]

    page_url = APPSTORE_PAGE.format(cc=storefront)
    reviews: list[LiveReview] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stars = _to_float(_label(entry.get("im:rating")))
        if stars is None:
            continue
        body = _label(entry.get("content")) or _label(entry.get("title"))
        excerpt = clip_excerpt(body)
        if not is_quotable(excerpt):
            continue
        author = entry.get("author") if isinstance(entry.get("author"), dict) else {}
        reviews.append(
            LiveReview(
                source_name=SOURCE_APPSTORE,
                url=page_url,
                excerpt=excerpt,
                review_date=_parse_iso_date(_label(entry.get("updated"))),
                rating=stars * 2,  # 1-5 stars -> 2-10 on the table's scale
                author=_clip(_label(author.get("name")) or None, _MAX_AUTHOR),
                rating_note=f"{stars:.0f}/5 App Store ({storefront.upper()})",
                extra={"storefront": storefront},
            )
        )
    return reviews


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Skytrax (airlinequality.com) -- schema.org microdata in plain HTML
# --------------------------------------------------------------------------

# Reviews open with "✅ Trip Verified |" or "Not Verified |" -- source metadata,
# not the passenger's words.
_VERIFIED_PREFIX_RE = re.compile(r"^[^|]{0,40}\bverified\b[^|]{0,20}\|\s*", re.IGNORECASE)
_REVIEW_ID_RE = re.compile(r"\breview-(\d+)\b")


def parse_skytrax(html: str, page_url: str = SKYTRAX_BASE) -> list[LiveReview]:
    """<article itemprop="review"> blocks -> LiveReview.

    The permalink is always built off the *base* listing URL plus the review's
    own anchor, never off `page_url`: reviews slide from page 1 to page 2 as
    new ones land, and a page-dependent URL would re-insert them under a new
    dedupe key every time that happened.
    """
    soup = BeautifulSoup(html or "", "lxml")
    reviews: list[LiveReview] = []

    for article in soup.find_all("article", attrs={"itemprop": "review"}):
        body_el = article.find(attrs={"itemprop": "reviewBody"})
        if body_el is None:
            continue
        raw_body = _VERIFIED_PREFIX_RE.sub("", body_el.get_text(" ", strip=True))
        excerpt = clip_excerpt(raw_body)
        if not is_quotable(excerpt):
            continue

        rating = None
        rating_wrap = article.find(attrs={"itemprop": "reviewRating"})
        if rating_wrap is not None:
            rating_el = rating_wrap.find(attrs={"itemprop": "ratingValue"})
            if rating_el is not None:
                rating = _to_float(rating_el.get_text(strip=True))

        author = None
        author_el = article.find(attrs={"itemprop": "author"})
        if author_el is not None:
            name_el = author_el.find(attrs={"itemprop": "name"})
            author = (name_el or author_el).get_text(" ", strip=True)

        reviews.append(
            LiveReview(
                source_name=SOURCE_SKYTRAX,
                url=_skytrax_permalink(article, page_url),
                excerpt=excerpt,
                review_date=_skytrax_date(article),
                rating=rating,
                author=_clip(author, _MAX_AUTHOR),
                route=_clip(_skytrax_value(article, "route"), _MAX_ROUTE),
                rating_note=None if rating is None else f"{rating:.0f}/10 Skytrax",
                extra={
                    "cabin": _skytrax_value(article, "cabin_flown"),
                    "headline": _skytrax_headline(article),
                },
            )
        )
    return reviews


def _skytrax_permalink(article, page_url: str) -> str:
    match = _REVIEW_ID_RE.search(" ".join(article.get("class") or []))
    if match:
        return f"{SKYTRAX_BASE}#anchor{match.group(1)}"
    return page_url


def _skytrax_date(article) -> date | None:
    meta = article.find("meta", attrs={"itemprop": "datePublished"})
    if meta is not None and meta.get("content"):
        return _parse_iso_date(meta["content"])
    time_el = article.find("time", attrs={"datetime": True})
    if time_el is not None:
        return _parse_iso_date(time_el["datetime"])
    return None


def _skytrax_value(article, header_class: str) -> str | None:
    """Read one cell out of the per-review stats table (route, cabin, ...)."""
    header = article.find("td", class_=lambda c: bool(c) and header_class in c)
    if header is None:
        return None
    value = header.find_next_sibling("td")
    return value.get_text(" ", strip=True) if value is not None else None


def _skytrax_headline(article) -> str | None:
    headline = article.find(class_="text_header")
    return headline.get_text(" ", strip=True).strip('"') if headline is not None else None


# --------------------------------------------------------------------------
# Reddit r/TurkishAirlines .rss
# --------------------------------------------------------------------------

def parse_reddit(xml: str | bytes) -> list[LiveReview]:
    """Atom entries -> LiveReview. No scores here, so sentiment is heuristic.

    The RSS body is a rendered HTML table (thumbnail + post text + a "submitted
    by" footer); only the post's own <div class="md"> is quoted. Link-only and
    image-only posts fall back to the title.
    """
    parsed = feedparser.parse(xml)
    reviews: list[LiveReview] = []
    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        title = (entry.get("title") or "").strip()
        body = _reddit_body(_entry_html(entry)) or title
        excerpt = clip_excerpt(body)
        if not is_quotable(excerpt):
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        reviews.append(
            LiveReview(
                source_name=SOURCE_REDDIT,
                url=url,
                excerpt=excerpt,
                review_date=date(*published[:3]) if published else None,
                rating=None,
                author=_clip(_reddit_author(entry), _MAX_AUTHOR),
                extra={"title": title},
            )
        )
    return reviews


def _entry_html(entry) -> str:
    contents = entry.get("content") or []
    if contents:
        return contents[0].get("value", "")
    return entry.get("summary", "")


def _reddit_body(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    md = soup.find("div", class_="md")
    if md is None:
        return ""
    for anchor in md.find_all("a"):
        anchor.decompose()  # drops "[link]"/"[comments]" if they ever land inside
    return md.get_text(" ", strip=True)


def _reddit_author(entry) -> str | None:
    author = entry.get("author") or ""
    author = author.strip().lstrip("/")
    return author or None


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

async def fetch_appstore(client: httpx.AsyncClient) -> list[LiveReview]:
    reviews: list[LiveReview] = []
    for storefront in APPSTORE_STOREFRONTS:
        url = APPSTORE_RSS.format(cc=storefront)
        try:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # One storefront being unavailable must not cost us the other three.
            logger.warning("tk_reviews_appstore_failed", storefront=storefront, error=str(exc))
            continue
        reviews.extend(parse_appstore(payload, storefront))
    return reviews


async def fetch_skytrax(client: httpx.AsyncClient) -> list[LiveReview]:
    reviews: list[LiveReview] = []
    for page_url in SKYTRAX_PAGES:
        try:
            response = await client.get(page_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("tk_reviews_skytrax_failed", url=page_url, error=str(exc))
            continue
        reviews.extend(parse_skytrax(response.text, page_url))
    return reviews


async def fetch_reddit(client: httpx.AsyncClient) -> list[LiveReview]:
    response = await client.get(REDDIT_RSS)
    response.raise_for_status()
    return parse_reddit(response.content)


# source label -> coroutine returning its reviews. Patched in tests.
FETCHERS: dict[str, object] = {
    SOURCE_APPSTORE: fetch_appstore,
    SOURCE_SKYTRAX: fetch_skytrax,
    SOURCE_REDDIT: fetch_reddit,
}


# --------------------------------------------------------------------------
# Upsert
# --------------------------------------------------------------------------

async def refresh_tk_reviews(db: AsyncSession, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch every live source and insert what we have not seen before.

    Returns {"fetched": n, "inserted": n, "sources": {label: n}, "errors": {}}.
    Existing rows are left untouched: many of them are hand-curated in
    tk_reviews_seed.py (real Turkish translations, human theme tagging) and a
    machine pass must not overwrite that work.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": BROWSER_UA, "Accept-Language": "en;q=0.9"},
            follow_redirects=True,
        )

    fetched: list[LiveReview] = []
    per_source: dict[str, int] = {}
    errors: dict[str, str] = {}
    try:
        for label, fetcher in FETCHERS.items():
            try:
                source_reviews = await fetcher(client)
            except Exception as exc:  # noqa: BLE001 -- one dead source, not a dead run
                errors[label] = str(exc)
                per_source[label] = 0
                logger.warning("tk_reviews_source_failed", source=label, error=str(exc))
                continue
            per_source[label] = len(source_reviews)
            fetched.extend(source_reviews)
    finally:
        if owns_client:
            await client.aclose()

    inserted = await _store(db, fetched)
    logger.info(
        "tk_reviews_refreshed",
        fetched=len(fetched),
        inserted=inserted,
        sources=per_source,
        errors=sorted(errors),
    )
    return {
        "fetched": len(fetched),
        "inserted": inserted,
        "sources": per_source,
        "errors": errors,
    }


async def _store(db: AsyncSession, reviews: list[LiveReview]) -> int:
    """Insert unseen reviews. Idempotent on sha256(url+excerpt), plus the
    near-duplicate guard so a curated seed row and its live twin do not both
    show up on the page under different listing URLs."""
    existing = (await db.execute(select(TkReview.dedupe_key, TkReview.excerpt))).all()
    seen_keys = {row[0] for row in existing}
    seen_texts = [_squash(row[1]) for row in existing]

    inserted = 0
    for review in reviews:
        key = dedupe_key(review.url, review.excerpt)
        if key in seen_keys or is_near_duplicate(review.excerpt, seen_texts):
            continue
        seen_keys.add(key)
        seen_texts.append(_squash(review.excerpt))

        db.add(
            TkReview(
                source_name=review.source_name,
                url=review.url,
                dedupe_key=key,
                review_date=review.review_date,
                rating=review.rating,
                author=review.author,
                route=review.route,
                excerpt=review.excerpt,
                # No LLM on this path: the BİZ page renders `excerpt_tr or
                # excerpt`, so a NULL here shows the original quote rather than
                # a machine translation nobody reviewed.
                excerpt_tr=None,
                sentiment=await sentiment_for(review.rating, review.excerpt),
                themes=tag_themes(review.excerpt),
            )
        )
        inserted += 1

    await db.commit()
    return inserted
