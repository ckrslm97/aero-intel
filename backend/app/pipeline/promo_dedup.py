"""Same campaign, two detection paths -- match them by substance, then merge.

`promotions` is keyed on `url`, which is the right idempotency key for each
detection path on its own but is blind to the thing that actually matters: the
airline's own campaign page and a news report *about that campaign* carry
different URLs, so the same real-world campaign lands twice. Live example, both
rows from one refresh 16 seconds apart:

    Pegasus: Kuzey Kıbrıs uçuşları salı-perşembe %40 indirimli   (news, no dates)
      .../kuzey-kibris-ucuslari-salidan-persembeye-40-indirimli
    Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!    (airline, dated)
      .../kuzey-kibris-ucuslari-salidan-persembeye-40-indirimli-2026

The timeline drew that as a dated bar AND a dateless point marker -- one
campaign, two lanes' worth of ink, on the product's flagship view.

So every write path asks this module first, and a match merges instead of
inserting. Direction of the merge matters as much as detecting it: the surviving
row takes the richest value per field, the airline's own value for anything the
airline is authoritative about (its sale window, its rate, its URL), and the
EARLIEST `detected_at` of the two -- that timestamp drives the "Yeni" badge, so
adopting the later sighting would flash a week-old campaign as new.

Why the bar for a match is set high
-----------------------------------
A false merge is not a cosmetic error: it deletes a competitor's campaign from
the timeline, silently, and there is nothing left on screen to notice. A missed
duplicate merely draws one campaign twice, which is visible and self-correcting
on the next run. Every threshold here is therefore chosen to fail closed, and a
match has to clear four independent gates -- same carrier, similar title,
non-conflicting subject, plausible timing.

Why not `pipeline/dedup.py`
---------------------------
That module's Jaccard machinery is the right *shape* and this one deliberately
copies it (token Jaccard on titles, plus a "do these two actually name the same
subject" veto modelled on its `_mentions_conflict`). What cannot be reused is
its normalizer: `pipeline/hashing.normalize_text` strips everything outside
`[a-z0-9\\s]`, which is fine for the English trade press it was built for and
destructive here -- "Kuzey Kıbrıs" becomes "kuzey k br s" and "İNDİRİM" becomes
"i ndirim" (Python lowercases "İ" to "i" plus a combining dot). On article
bodies of several hundred words that noise averages out; on a seven-word
campaign title it is most of the signal. The rest of that module -- MinHash,
LSH, the article `is_duplicate` graph -- solves a problem this table does not
have: `promotions` holds hundreds of rows, not hundreds of thousands, and a
duplicate here must be *merged away*, not flagged and kept.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.promotion import Promotion
from app.pipeline.text_tr import STEM_LEN, stem_tokens, tr_normalize

logger = get_logger(__name__)

# Token-Jaccard floor for two titles to be "the same campaign". Measured on the
# live pair above: 0.88. Measured on the nearest genuine non-duplicates in the
# same table -- Pegasus's near-identically-named partnership campaigns
# ("Pegasus BolBol & Polira İş Birliği" vs "Pegasus BolBol ve Teknevia İş
# Birliği") -- 0.57, because everything except the partner's name is shared
# boilerplate. Those are caught by the subject veto below rather than by this
# number, but the floor sits above the level where two unrelated campaigns can
# collide on filler alone.
TITLE_SIMILARITY_MIN = 0.55

# How far apart two sightings of one campaign can be when neither row states a
# sale window (with windows, overlap is the better test -- see _time_plausible).
# Press coverage clusters within days of a launch; six weeks is generous for
# that and still far short of the year that separates a campaign from its
# annual re-run, which is the false merge this gate exists to prevent.
MAX_DETECTION_GAP = timedelta(days=45)

# Turkish is agglutinative: "uçuşlarında", "uçuşları" and "uçuşlar" are the same
# word wearing three case endings, and campaign copy inflects freely. Comparing
# fixed-length prefixes is the cheap standard fix and costs nothing in
# precision here, because the subject veto works on the same stems.

# Source names that mean "the airline said this about its own campaign". The
# authority that follows from it is narrow and deliberate: dates, rate and the
# canonical URL. It does not make the airline's marketing copy a better summary
# than a journalist's, so summaries are picked on substance instead.
AIRLINE_PAGE_SOURCES = frozenset({"Pegasus kampanya sayfası"})


# Words that appear in campaign titles regardless of WHICH campaign it is.
# Two kinds: marketing/structural filler, and the carrier and loyalty-programme
# names -- every Pegasus campaign says "Pegasus" and half of them say "BolBol",
# so neither tells two Pegasus campaigns apart. Only what remains after these
# are removed can veto a merge.
_FILLER = (
    "kampanya", "kampanyası", "kampanyalı", "indirim", "indirimli", "indirimi",
    "fırsat", "fırsatı", "fırsatları", "bilet", "bileti", "biletleri",
    "biletlerinde", "uçuş", "uçuşu", "uçuşları", "uçuşlarında", "uçak", "yolcu",
    "özel", "yeni", "varan", "kadar", "ile", "ve", "için", "son", "tüm",
    "seçili", "geçerli", "başlayan", "fiyat", "fiyatları", "fiyatlarla",
    "hatlarında", "seferlerinde", "uygulama", "uygulamaya", "müjde", "müjdesi",
    "duyurdu", "başladı", "sunuyor", "avantaj", "iş", "birliği", "işbirliği",
    "üyelerine", "üyelere", "dönem", "dönemi",
    "pegasus", "turkish", "airlines", "thy", "ajet", "emirates", "qatar",
    "etihad", "lufthansa", "klm", "british", "airways", "air", "france",
    "bolbol", "miles", "smiles", "skywards", "avios", "sale", "off", "up", "to",
)


def title_tokens(title: str) -> set[str]:
    """Stemmed content tokens for a campaign title."""
    return stem_tokens(title)


GENERIC_TOKENS = frozenset(tr_normalize(word)[:STEM_LEN] for word in _FILLER)


def title_similarity(title_a: str, title_b: str) -> float:
    """Jaccard over stemmed title tokens, 0.0 when either side is empty."""
    tokens_a, tokens_b = title_tokens(title_a), title_tokens(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def subjects_conflict(title_a: str, title_b: str) -> bool:
    """True when the titles name different things.

    Same idea as dedup.py's `_mentions_conflict` (there: aircraft models,
    manufacturers, counterparty acronyms), applied to what identifies a
    campaign: strip the filler and the carrier's own name, and whatever is left
    is the destination, the partner, the segment or the rate. If both sides
    have such tokens and they share none, these are two campaigns that merely
    read alike -- "Pegasus BolBol & Polira İş Birliği" and "Pegasus BolBol ve
    Teknevia İş Birliği" differ by one word out of six and are entirely
    different deals.
    """
    distinct_a = title_tokens(title_a) - GENERIC_TOKENS
    distinct_b = title_tokens(title_b) - GENERIC_TOKENS
    if not distinct_a or not distinct_b:
        # One side is nothing but boilerplate; it cannot contradict anything.
        return False
    return not (distinct_a & distinct_b)


@dataclass
class PromoCandidate:
    """A campaign about to be written, from either detection path.

    Mirrors the writable columns of `Promotion` so matching and merging can be
    done before the row exists -- and so an existing row can be turned back
    into one (`candidate_from_row`) when the same logic runs over the table.
    """

    airline_code: str
    airline_name: str
    title_tr: str
    summary_tr: str
    url: str
    source_name: str
    detected_at: datetime
    discount_pct: int | None = None
    markets: str | None = None
    sale_starts: date | None = None
    sale_ends: date | None = None
    travel_starts: date | None = None
    travel_ends: date | None = None
    region: str | None = None


def candidate_from_row(row: Promotion) -> PromoCandidate:
    return PromoCandidate(
        airline_code=row.airline_code,
        airline_name=row.airline_name,
        title_tr=row.title_tr,
        summary_tr=row.summary_tr or "",
        url=row.url,
        source_name=row.source_name,
        detected_at=row.detected_at,
        discount_pct=row.discount_pct,
        markets=row.markets,
        sale_starts=row.sale_starts,
        sale_ends=row.sale_ends,
        travel_starts=row.travel_starts,
        travel_ends=row.travel_ends,
        region=row.region,
    )


def is_airline_sourced(source_name: str | None) -> bool:
    return (source_name or "") in AIRLINE_PAGE_SOURCES


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _windows_overlap(
    a_start: date | None, a_end: date | None, b_start: date | None, b_end: date | None
) -> bool | None:
    """Do two half-known sale windows intersect? None when one side has none.

    A missing edge is treated as open, which is how the timeline draws it: a
    campaign with no stated end has not been said to stop.
    """
    if (a_start is None and a_end is None) or (b_start is None and b_end is None):
        return None
    return (a_start or date.min) <= (b_end or date.max) and (b_start or date.min) <= (
        a_end or date.max
    )


def _time_plausible(candidate: PromoCandidate, row: Promotion) -> bool:
    """Could these two be the same campaign, in time?

    When both sides state a window, disjoint windows settle it: an August sale
    and next August's re-run of the same sale, with the same title, are two
    campaigns. When one side states none -- the common case, since press
    coverage usually omits dates -- fall back to how far apart we saw them.
    """
    overlap = _windows_overlap(
        candidate.sale_starts, candidate.sale_ends, row.sale_starts, row.sale_ends
    )
    if overlap is not None:
        return overlap
    return abs(_aware(candidate.detected_at) - _aware(row.detected_at)) <= MAX_DETECTION_GAP


def is_duplicate(candidate: PromoCandidate, row: Promotion) -> bool:
    """Four gates, all of which must pass. Order is cheapest-first."""
    if candidate.airline_code != row.airline_code:
        # Never across carriers, at any similarity: two airlines running the
        # same "%40 indirim" headline is a price war, not a duplicate.
        return False
    if candidate.url == row.url:
        return False  # the URL key already handles this one
    if (
        candidate.discount_pct is not None
        and row.discount_pct is not None
        and candidate.discount_pct != row.discount_pct
    ):
        # Both sources state a rate and they disagree -> two campaigns, or one
        # we understand too poorly to merge safely.
        return False
    if title_similarity(candidate.title_tr, row.title_tr) < TITLE_SIMILARITY_MIN:
        return False
    if subjects_conflict(candidate.title_tr, row.title_tr):
        return False
    return _time_plausible(candidate, row)


def best_match(candidate: PromoCandidate, rows: list[Promotion]) -> Promotion | None:
    """The most similar row that clears every gate, or None."""
    matches = [row for row in rows if is_duplicate(candidate, row)]
    if not matches:
        return None
    return max(matches, key=lambda row: title_similarity(candidate.title_tr, row.title_tr))


async def find_duplicate(db: AsyncSession, candidate: PromoCandidate) -> Promotion | None:
    """Scan this carrier's campaigns for one the candidate already is.

    A plain scan, not an index: `promotions` is a few hundred rows and one
    carrier's slice is a few dozen. Anything cleverer would be a cache to keep
    correct for no measurable gain.
    """
    rows = list(
        (
            await db.execute(
                select(Promotion).where(Promotion.airline_code == candidate.airline_code)
            )
        )
        .scalars()
        .all()
    )
    return best_match(candidate, rows)


def _richer_text(current: str | None, incoming: str | None, prefer_incoming: bool) -> str:
    """Longer wins, because a summary's value is what it tells you. Ties go to
    the preferred source rather than to whichever ran last."""
    current, incoming = (current or "").strip(), (incoming or "").strip()
    if not incoming:
        return current
    if not current:
        return incoming
    if len(incoming) == len(current):
        return incoming if prefer_incoming else current
    return incoming if len(incoming) > len(current) else current


def _pick(current, incoming, prefer_incoming: bool):
    """Non-null beats null; when both are stated, the preferred source wins."""
    if incoming is None:
        return current
    if current is None:
        return incoming
    return incoming if prefer_incoming else current


def merge_candidate(
    row: Promotion, candidate: PromoCandidate, prefer_candidate: bool | None = None
) -> None:
    """Fold `candidate` into `row` so the row ends up the richest of the two.

    `prefer_candidate` decides who wins a field both sides state; None (the
    default) reads it off the sources -- the airline's own page outranks a news
    report about it, and between two rows of equal standing the incumbent wins
    so a refresh is stable rather than alternating. Callers refreshing a row
    from its own source pass True: that is the same source restating itself,
    where the newer reading is the better one.

    Null never overwrites a value either way. A source that has stopped
    mentioning a date has not retracted it, and the row may be carrying that
    date on behalf of a source that never comes back through this path.
    """
    if prefer_candidate is None:
        prefer_candidate = is_airline_sourced(candidate.source_name) and not is_airline_sourced(
            row.source_name
        )

    if candidate.title_tr and (prefer_candidate or not row.title_tr):
        row.title_tr = candidate.title_tr[:300]
    row.summary_tr = _richer_text(row.summary_tr, candidate.summary_tr, prefer_candidate)

    row.discount_pct = _pick(row.discount_pct, candidate.discount_pct, prefer_candidate)
    row.sale_starts = _pick(row.sale_starts, candidate.sale_starts, prefer_candidate)
    row.sale_ends = _pick(row.sale_ends, candidate.sale_ends, prefer_candidate)
    row.travel_starts = _pick(row.travel_starts, candidate.travel_starts, prefer_candidate)
    row.travel_ends = _pick(row.travel_ends, candidate.travel_ends, prefer_candidate)
    row.region = _pick(row.region, candidate.region, prefer_candidate)

    # Markets are a list flattened into a string; more entries is more coverage.
    if candidate.markets:
        if not row.markets:
            row.markets = candidate.markets
        elif prefer_candidate or len(candidate.markets.split(",")) > len(
            row.markets.split(",")
        ):
            row.markets = candidate.markets

    # URL and source name travel together -- a row must not cite one source's
    # name next to another's link. The airline's campaign page is the canonical
    # destination for its own campaign, so it takes both or neither.
    if prefer_candidate and candidate.url:
        row.url = candidate.url[:500]
        row.source_name = candidate.source_name
        row.airline_name = candidate.airline_name or row.airline_name

    # Earliest sighting wins: we genuinely first saw this campaign then, and
    # this is what the "Yeni" badge and the 48h banner read.
    row.detected_at = min(_aware(row.detected_at), _aware(candidate.detected_at))


async def dedupe_existing_promotions(db: AsyncSession) -> dict[str, int]:
    """Collapse duplicates already sitting in the table.

    The matching gates are the same ones the write paths use, so this is a
    backfill of the fix rather than a second policy. Rows are walked oldest
    sighting first, so the row that survives is the one the timeline has been
    showing, and a later duplicate is folded into it -- taking the later row's
    URL and dates only when the later row is the airline's own page.
    """
    rows = list(
        (await db.execute(select(Promotion).order_by(Promotion.detected_at.asc())))
        .scalars()
        .all()
    )

    kept: list[Promotion] = []
    merged = 0
    for row in rows:
        candidate = candidate_from_row(row)
        match = best_match(candidate, kept)
        if match is None:
            kept.append(row)
            continue
        # Delete before merging: the survivor may adopt this row's URL, and
        # `promotions.url` is unique, so both cannot hold it even momentarily.
        await db.delete(row)
        await db.flush()
        merge_candidate(match, candidate)
        await db.flush()
        merged += 1
        logger.info(
            "promotion_duplicate_merged",
            airline=match.airline_code,
            kept_id=str(match.id),
            absorbed_url=candidate.url,
            now_at=match.url,
        )

    await db.commit()
    return {"scanned": len(rows), "merged": merged, "remaining": len(kept)}


async def mark_legacy_campaigns_superseded(db: AsyncSession) -> dict[str, int]:
    """Faz 13/K8: the ~124 rows the old, unvalidated pipeline published stay
    in the table (never destroyed -- see the plan's own "yerini aldı" wording,
    K8) but stop being served, so the before/after comparison stays checkable.

    `validation_state` is the marker: it's a Faz 3 column, only ever written
    by campaign_airline.py's build_promotion(), so a row where it is still
    null was never seen by the new validation layer at all -- not "validated
    and found incomplete" (that's validation_state="incomplete", a real,
    still-served state), but "predates validation entirely". Idempotent: a
    row already marked superseded is left alone.
    """
    rows = (
        await db.execute(
            select(Promotion).where(
                Promotion.validation_state.is_(None),
                Promotion.superseded_at.is_(None),
            )
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    for row in rows:
        row.superseded_at = now

    await db.commit()
    logger.info("legacy_campaigns_superseded", count=len(rows))
    return {"marked_superseded": len(rows)}
