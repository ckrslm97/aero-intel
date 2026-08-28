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

What a merge leaves behind
--------------------------
A merge used to be a silent overwrite: the row changed and nothing recorded
that it had. Since PR5 every merge also answers two questions in writing.

*What changed* -- `merge_candidate` returns a `changed_fields` diff and
`record_version` turns it into a `campaign_versions` row, so "the rival moved
its deadline" survives the write instead of being erased by it. A scan that
finds nothing changed writes no version row at all; version numbers count
edits, not sightings.

*Who said so* -- `ensure_source_row` files every URL that contributed to a row
in `campaign_sources`, including the row's own. That is what makes a resolved
conflict explicable ("the official page says 40%, the trade report said 30%")
and what feeds the corroboration input of the confidence score.

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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.pipeline.confidence import HIGH_THRESHOLD, rescore_with_corroboration
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

# Every carrier the deep scan reads writes its source name the same way --
# "Emirates kampanya sayfası", "Turkish Airlines kampanya sayfası" (see
# pipeline/campaign_extract.py) -- and Pegasus, named above before that path
# existed, already follows it. Matching the suffix rather than enumerating the
# carriers keeps this module from importing the carrier registry to answer a
# question about a string, and means adding an eighth carrier does not silently
# demote its own campaign page below a news report about it.
AIRLINE_PAGE_SUFFIX = "kampanya sayfası"

# `campaign_sources.source_tier`, as an ordering. Three values, not five: this
# is the "who wins a disagreement" ladder, and the five tiers in
# pipeline/confidence.py answer a different question (how much a source moves a
# score). A regulator and a trade outlet score differently there and are the
# same thing here -- somebody reporting on a campaign they are not running.
SOURCE_TIER_RANK: dict[str, int] = {"official": 3, "newsroom": 2, "secondary": 1}
DEFAULT_SOURCE_TIER = "secondary"

# How an article's source tier (pipeline/confidence.SOURCE_TIER_SCORES) becomes
# a campaign source tier. An article is secondary reporting *about* a campaign
# even when the outlet is a good one -- a trade journalist reading the same
# campaign page we read does not outrank the page. The single exception is a
# source that IS the carrier, which in this codebase is exactly what the
# "official" article tier means ("the airline's or airport's own announcement"),
# and that lands on `newsroom` rather than `official`: the carrier's press
# release is first-party, but `official` is reserved for the page that actually
# sells the campaign and states its terms.
ARTICLE_TIER_TO_CAMPAIGN_TIER: dict[str, str] = {"official": "newsroom"}

# Fields where two sources disagreeing is a fact an analyst has to see, rather
# than a merge detail. Chosen for what they change on screen: the rate, either
# window, and what kind of campaign this is. Title and summary are deliberately
# absent -- two sources always word a campaign differently and always will.
MATERIAL_FIELDS: tuple[str, ...] = (
    "discount_pct",
    "sale_starts",
    "sale_ends",
    "travel_starts",
    "travel_ends",
    "campaign_type",
)


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
    #: A v2 column, carried here so a disagreement about what kind of campaign
    #: this is resolves by source tier like every other material field instead
    #: of by whichever path wrote last.
    campaign_type: str | None = None
    #: official | newsroom | secondary. None means "read it off `source_name`",
    #: which is right for every path except the article one -- a news outlet's
    #: name says nothing about its standing, so runner.py passes the tier it
    #: already knows from `sources.tier`.
    source_tier: str | None = None


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
        campaign_type=row.campaign_type,
    )


def is_airline_sourced(source_name: str | None) -> bool:
    name = (source_name or "").strip()
    return name in AIRLINE_PAGE_SOURCES or name.casefold().endswith(AIRLINE_PAGE_SUFFIX)


def tier_for_source_name(source_name: str | None) -> str:
    """The campaign source tier a bare source name implies.

    Only two answers are reachable from a name alone: the carrier's own
    campaign page writes itself as "<carrier> kampanya sayfası", and everything
    else is somebody else's page. `newsroom` needs a fact a name does not carry
    (which channel of the carrier this is), so it is only ever passed in
    explicitly -- see `campaign_tier_for_article`.
    """
    return "official" if is_airline_sourced(source_name) else DEFAULT_SOURCE_TIER


def campaign_tier_for_article(article_tier: str | None) -> str:
    """An article's `sources.tier` as a campaign source tier. See the map."""
    return ARTICLE_TIER_TO_CAMPAIGN_TIER.get(article_tier or "", DEFAULT_SOURCE_TIER)


def _tier_rank(tier: str | None) -> int:
    return SOURCE_TIER_RANK.get(tier or "", SOURCE_TIER_RANK[DEFAULT_SOURCE_TIER])


def candidate_tier(candidate: PromoCandidate) -> str:
    return candidate.source_tier or tier_for_source_name(candidate.source_name)


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


def _jsonable(value: Any) -> Any:
    """The form a value takes inside `changed_fields`.

    JSONB will not take a date and Python will not compare a stored ISO string
    to one, so dates and datetimes are written as ISO strings and read back as
    strings by everything downstream. Datetimes are made tz-aware first: the
    same instant written twice, once with a zone and once without, must not
    read as two different values in a diff.
    """
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class _Diff:
    """Applies field writes to a row and remembers the ones that changed.

    The shape it produces per field:

        {"previous": <old>, "new": <kept>}                       an ordinary change
        {"previous": <old>, "new": <kept>, "conflict": True,
         "rejected": <loser>, "rejected_source": <url>,
         "rejected_source_tier": <tier>}                          a resolved conflict

    An entry where `previous == new` and `conflict` is set is not a no-op: it
    is the incumbent winning a disagreement, and it is written precisely
    because "we were told 30% and kept 40%" is the thing an analyst needs to
    be able to look up. Nothing else ever writes an entry that did not move.
    """

    def __init__(self, row: Promotion) -> None:
        self._row = row
        self.fields: dict[str, dict] = {}

    def set(self, name: str, value: Any) -> None:
        previous = getattr(self._row, name)
        if previous == value:
            return
        setattr(self._row, name, value)
        entry = self.fields.setdefault(name, {"previous": _jsonable(previous)})
        entry["new"] = _jsonable(value)

    def note_conflict(
        self, name: str, *, rejected: Any, source_url: str | None, source_tier: str
    ) -> None:
        """Record the losing value. Called before the merge writes anything, so
        the row still holds its own value and `previous`/`new` can be seeded
        from it -- a later `set()` for the same field overwrites `new` when the
        candidate is the side that won."""
        previous = _jsonable(getattr(self._row, name))
        entry = self.fields.setdefault(name, {"previous": previous, "new": previous})
        entry["conflict"] = True
        entry["rejected"] = _jsonable(rejected)
        entry["rejected_source"] = source_url
        entry["rejected_source_tier"] = source_tier


def merge_candidate(
    row: Promotion, candidate: PromoCandidate, prefer_candidate: bool | None = None
) -> dict[str, dict]:
    """Fold `candidate` into `row` so the row ends up the richest of the two.

    Returns the diff of what it actually changed -- `{field: {"previous": ...,
    "new": ...}}`, JSON-serializable, ready for `record_version`. Empty means
    the row already said everything the candidate does, which is the ordinary
    outcome of re-scanning an unchanged page and must not produce a version
    row. The mutation is still in place, so a caller that only wants the merge
    can ignore the return.

    `prefer_candidate` decides who wins a field both sides state; None (the
    default) reads it off the source tiers -- the airline's own page outranks a
    news report about it, and between two sources of equal standing the
    incumbent wins so a refresh is stable rather than alternating. Callers
    refreshing a row from its own source pass True: that is the same source
    restating itself, where the newer reading is the better one.

    Conflicts (both sides state a material field and disagree) are only a
    *conflict* in the default mode. When the caller passes `prefer_candidate`
    explicitly it has told us the two readings come from one source, and one
    source revising itself is a change, not a disagreement -- flagging it would
    fill `conflict_detected` with every carrier that ever extended a deadline.

    Null never overwrites a value either way. A source that has stopped
    mentioning a date has not retracted it, and the row may be carrying that
    date on behalf of a source that never comes back through this path.
    """
    cross_source = prefer_candidate is None
    incumbent_tier = tier_for_source_name(row.source_name)
    incoming_tier = candidate_tier(candidate)
    if prefer_candidate is None:
        prefer_candidate = _tier_rank(incoming_tier) > _tier_rank(incumbent_tier)

    diff = _Diff(row)
    if cross_source:
        # Before anything moves: the incumbent's URL is what a rejected value
        # has to be attributed to, and a merge may be about to overwrite it.
        _flag_conflicts(
            row,
            candidate,
            diff,
            prefer_candidate=prefer_candidate,
            incumbent_url=row.url,
            incumbent_tier=incumbent_tier,
            incoming_tier=incoming_tier,
        )

    if candidate.title_tr and (prefer_candidate or not row.title_tr):
        diff.set("title_tr", candidate.title_tr[:300])
    diff.set(
        "summary_tr", _richer_text(row.summary_tr, candidate.summary_tr, prefer_candidate)
    )

    diff.set("discount_pct", _pick(row.discount_pct, candidate.discount_pct, prefer_candidate))
    diff.set("sale_starts", _pick(row.sale_starts, candidate.sale_starts, prefer_candidate))
    diff.set("sale_ends", _pick(row.sale_ends, candidate.sale_ends, prefer_candidate))
    diff.set(
        "travel_starts", _pick(row.travel_starts, candidate.travel_starts, prefer_candidate)
    )
    diff.set("travel_ends", _pick(row.travel_ends, candidate.travel_ends, prefer_candidate))
    diff.set("region", _pick(row.region, candidate.region, prefer_candidate))
    diff.set(
        "campaign_type", _pick(row.campaign_type, candidate.campaign_type, prefer_candidate)
    )

    # Markets are a list flattened into a string; more entries is more coverage.
    if candidate.markets:
        if not row.markets:
            diff.set("markets", candidate.markets)
        elif prefer_candidate or len(candidate.markets.split(",")) > len(
            row.markets.split(",")
        ):
            diff.set("markets", candidate.markets)

    # URL and source name travel together -- a row must not cite one source's
    # name next to another's link. The airline's campaign page is the canonical
    # destination for its own campaign, so it takes both or neither.
    if prefer_candidate and candidate.url:
        diff.set("url", candidate.url[:500])
        diff.set("source_name", candidate.source_name)
        diff.set("airline_name", candidate.airline_name or row.airline_name)

    # Earliest sighting wins: we genuinely first saw this campaign then, and
    # this is what the "Yeni" badge and the 48h banner read.
    earliest = min(_aware(row.detected_at), _aware(candidate.detected_at))
    if _aware(row.detected_at) != earliest:
        diff.set("detected_at", earliest)
    else:
        # Assigned unconditionally, as it always was: the value is identical,
        # but a naive column value becomes aware here and downstream comparisons
        # rely on that.
        row.detected_at = earliest

    return diff.fields


def _flag_conflicts(
    row: Promotion,
    candidate: PromoCandidate,
    diff: _Diff,
    *,
    prefer_candidate: bool,
    incumbent_url: str | None,
    incumbent_tier: str,
    incoming_tier: str,
) -> None:
    """Record every material field the two sources genuinely disagree on.

    Resolution is not decided here -- `_pick` already implements it, and it
    implements exactly the rule this needs: the more official source wins, ties
    go to the incumbent. This only makes the disagreement visible, by flagging
    the row and writing the losing value into the diff so the version row
    carries both sides.

    Note which disagreements can actually reach this function: `is_duplicate`
    refuses to match two rows whose stated discounts differ, so a rate conflict
    only arrives through a caller merging without that gate. Dates and
    campaign_type are the live cases -- windows may overlap and still disagree
    about where they end, which is precisely the "the rival moved its deadline"
    signal this whole table exists for.
    """
    for name in MATERIAL_FIELDS:
        current = getattr(row, name)
        incoming = getattr(candidate, name)
        if current is None or incoming is None or current == incoming:
            continue
        row.conflict_detected = True
        if prefer_candidate:
            diff.note_conflict(
                name,
                rejected=current,
                source_url=incumbent_url,
                source_tier=incumbent_tier,
            )
        else:
            diff.note_conflict(
                name,
                rejected=incoming,
                source_url=candidate.url,
                source_tier=incoming_tier,
            )
        logger.info(
            "promotion_conflict_detected",
            airline=row.airline_code,
            field=name,
            kept_tier=incoming_tier if prefer_candidate else incumbent_tier,
            rejected_tier=incumbent_tier if prefer_candidate else incoming_tier,
        )


def apply_updates(row: Promotion, updates: Mapping[str, Any]) -> dict[str, dict]:
    """Write `updates` onto `row` and return the same diff `merge_candidate` does.

    For the write paths that do not merge anything -- a scraper re-reading the
    page a row was created from, where the incoming reading simply wins -- so
    that "the page changed" is versioned there too rather than only where two
    sources meet.
    """
    diff = _Diff(row)
    for name, value in updates.items():
        diff.set(name, value)
    return diff.fields


# --- provenance: what changed, and who said so -------------------------------


async def record_version(
    db: AsyncSession,
    promotion: Promotion,
    changed_fields: Mapping[str, dict],
    *,
    source_url: str | None = None,
    now: datetime | None = None,
) -> CampaignVersion | None:
    """Turn a merge's diff into a `campaign_versions` row. None when empty.

    An empty diff is the common case -- a page re-scanned unchanged -- and it
    writes nothing at all: version numbers count edits, not sightings, and a
    row per sighting would bury the two edits a month that matter under sixty
    that do not. `last_seen_at` is the caller's job and moves either way.

    **Creation writes no version row, deliberately.** A version records a
    change to something that already existed; there is no "previous" for a
    campaign's first sighting, and `{field: {"previous": null, "new": ...}}`
    for every column would be a snapshot wearing a diff's clothes. When the
    campaign was first seen is already stored, on the row itself, in
    `first_seen_at` -- so version 1 means the first time it *moved*.

    Numbering is max+1 rather than a sequence, because the numbers have to be
    dense and per campaign. That read-then-write is not atomic; what makes it
    safe here is that every writer runs inside a GitHub Actions concurrency
    group (one deep-scan, one promotions job at a time), and if two ever did
    overlap the UniqueConstraint on (promotion_id, version_no) turns the race
    into a failed insert rather than a silently forked history.
    """
    if not changed_fields:
        return None

    highest = (
        await db.execute(
            select(func.max(CampaignVersion.version_no)).where(
                CampaignVersion.promotion_id == promotion.id
            )
        )
    ).scalar()

    version = CampaignVersion(
        promotion_id=promotion.id,
        version_no=(highest or 0) + 1,
        changed_fields=dict(changed_fields),
        source_url=source_url[:500] if source_url else None,
    )
    db.add(version)
    promotion.last_changed_at = now or datetime.now(timezone.utc)
    await db.flush()
    logger.info(
        "campaign_version_recorded",
        promotion_id=str(promotion.id),
        version_no=version.version_no,
        fields=sorted(changed_fields),
    )
    return version


async def ensure_source_row(
    db: AsyncSession,
    promotion: Promotion,
    *,
    url: str,
    source_name: str | None = None,
    tier: str | None = None,
    quality: float | None = None,
    seen_at: datetime | None = None,
    content_hash: str | None = None,
    page_published_at: date | None = None,
    raw_excerpt: str | None = None,
) -> tuple[CampaignSource, bool]:
    """Upsert one contributing page. Returns (row, created).

    Called for the promotion's own URL at insert time as well as for every URL
    a merge folds in, which is what makes "a campaign has at least one recorded
    source" true rather than aspirational. Re-sighting an existing URL moves
    `last_seen_at` and refreshes the hash; it never adds a row, because the
    corroboration count must mean "how many pages said this", not "how many
    times we looked".
    """
    moment = seen_at or datetime.now(timezone.utc)
    trimmed = url[:500]
    existing = (
        await db.execute(
            select(CampaignSource).where(
                CampaignSource.promotion_id == promotion.id,
                CampaignSource.url == trimmed,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.last_seen_at = moment
        if content_hash:
            existing.content_hash = content_hash
        # Fill-only for the descriptive columns: a later sighting that knows
        # less about a page must not erase what an earlier one knew.
        for column, value in (
            ("source_name", source_name),
            ("source_tier", tier),
            ("source_quality", quality),
            ("page_published_at", page_published_at),
            ("raw_excerpt", raw_excerpt),
        ):
            if value is not None and getattr(existing, column) is None:
                setattr(existing, column, value)
        await db.flush()
        return existing, False

    created = CampaignSource(
        promotion_id=promotion.id,
        url=trimmed,
        source_name=source_name[:120] if source_name else None,
        source_tier=tier or tier_for_source_name(source_name),
        source_quality=quality,
        page_published_at=page_published_at,
        content_hash=content_hash,
        first_seen_at=moment,
        last_seen_at=moment,
        raw_excerpt=raw_excerpt,
    )
    db.add(created)
    await db.flush()
    return created, True


async def count_sources(db: AsyncSession, promotion: Promotion) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(CampaignSource)
                .where(CampaignSource.promotion_id == promotion.id)
            )
        ).scalar()
        or 0
    )


async def rescore_for_corroboration(db: AsyncSession, promotion: Promotion) -> bool:
    """Re-score a row whose recorded source count changed. True if it moved.

    Only the corroboration input is revisited. Everything else in the stored
    score -- the tier that produced it, how much the model quoted, how complete
    the row is -- was a judgement about a reading, and a second page agreeing is
    not new evidence about any of those. It IS evidence that the campaign is
    real, which is exactly what `corroboration` weighs.

    A single source is left alone: every score in the table was already
    computed with `source_count=1`, so "re-scoring" it would be arithmetic with
    no new information, and back-filling a source row for a legacy campaign
    would silently rewrite its score.
    """
    if promotion.confidence_detail is None:
        return False
    total = await count_sources(db, promotion)
    if total < 2:
        return False

    rescored = rescore_with_corroboration(promotion.confidence_detail, source_count=total)
    if rescored is None or rescored.score == promotion.confidence_score:
        return False

    promotion.confidence_score = rescored.score
    promotion.confidence_band = rescored.band
    promotion.confidence_detail = rescored.as_detail()
    if promotion.review_required is not None:
        # Same threshold the extraction chain uses. Only touched on rows that
        # have a review flag at all: giving a legacy row one here would put it
        # in a queue it was never part of.
        promotion.review_required = rescored.score < HIGH_THRESHOLD
    logger.info(
        "campaign_confidence_rescored",
        promotion_id=str(promotion.id),
        sources=total,
        score=round(rescored.score, 4),
        band=rescored.band,
    )
    return True


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
        survivor_url, survivor_source = match.url, match.source_name
        await db.delete(row)
        await db.flush()
        changed = merge_candidate(match, candidate)
        await db.flush()
        # The absorbed row is gone from `promotions`; without this its URL --
        # the evidence that a second page carried this campaign -- would be
        # gone with it. Both sides are filed, then the survivor is re-scored
        # for the corroboration it just gained.
        await ensure_source_row(
            db, match, url=survivor_url, source_name=survivor_source, seen_at=match.detected_at
        )
        await ensure_source_row(
            db,
            match,
            url=candidate.url,
            source_name=candidate.source_name,
            tier=candidate_tier(candidate),
            seen_at=candidate.detected_at,
        )
        await rescore_for_corroboration(db, match)
        await record_version(db, match, changed, source_url=candidate.url)
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
