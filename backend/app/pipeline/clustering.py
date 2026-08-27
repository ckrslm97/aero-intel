"""Grouping articles into events.

The Gazete's unit becomes the event, not the article. Three outlets reporting
one merger used to be three rows, classified three separate times, and they
could disagree: `Jin Air, Air Busan and Air Seoul to merge` was filed under
`finance/equity` in English and `general` in German, from the same event on the
same day. That is not a threshold that needs tuning -- it is a schema problem,
and classifying once per event is the fix.

Why the existing MinHash pass was not enough on its own:

* **Turkish agglutination.** `THY'nin`, `THY'den` and `THY` are the same
  subject and share no token; `uçuş`, `uçuşlar` and `uçuşlarında` are one word
  written three ways. Jaccard over raw tokens is systematically lower for
  Turkish than for the same comparison in English, so the same threshold means
  something different depending on the language of the pair.
* **Names have several forms.** `THY`, `Türk Hava Yolları` and `Turkish
  Airlines` are one carrier. Until the gazetteer learned the Turkish names,
  none of them met.
* **Similarity alone over-merges.** Two Pegasus campaign announcements a month
  apart share almost all their vocabulary. Something has to say they are about
  different things, and shared subject entities is the honest test: two reports
  of one event name the same airline, airport or country.

So: normalise, then require a shared *subject* and a shared *distinctive
detail*.

A Jaccard threshold alone does not work here, and measuring showed why.
`THY'nin Lima hattı 2027'de açılıyor` and `Türk Hava Yolları Lima seferlerine
başlıyor` are plainly one event, and they score 0.29 -- because Turkish writes
the same idea with different suffixes and a different verb, so the union grows
while the intersection does not. Any threshold low enough to catch that pair is
low enough to merge unrelated stories about the same airline. The problem is
that Jaccard measures how similarly two headlines are *worded*, and what we
need to know is whether they are about the same *thing*.

What actually separates the cases is which tokens are shared. Two reports of one
event share a distinctive detail -- a city, a number, a route. Two unrelated
Pegasus campaigns share only the carrier and the vocabulary every campaign uses
("kampanya", "indirim", "yeni", "başladı"). So the test is: same subject
entities, plus at least one shared token that is neither the carrier nor
boilerplate.

A pair that is suspiciously similar with nothing to confirm it is left for a
cheap adjudication call rather than a coin flip -- see `needs_adjudication`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.gazetteer import AIRLINE_ALIASES
from app.pipeline.text_tr import jaccard, stem_tokens, tr_normalize

#: Floor for considering a pair at all. Deliberately low: it exists to stop
#: absurd comparisons, not to decide anything. The decision is made by the
#: subject/detail test below.
TITLE_SIMILARITY_MIN = 0.12

#: Above this, the titles are so close that entity overlap is not asked for.
#: Two headlines this similar are the same story even when neither names an
#: entity the gazetteer knows -- which is common for airport and regulator news.
TITLE_SIMILARITY_CERTAIN = 0.72

#: Alias substitution runs on normalised text, so the keys are already folded.
#: Longest first, so "türk hava yolları" is consumed before "hava" can be part
#: of a shorter match.
_ALIAS_BY_LENGTH: list[tuple[str, str]] = sorted(
    ((alias, code) for alias, (_name, code) in AIRLINE_ALIASES.items()),
    key=lambda pair: -len(pair[0]),
)


def canonicalize(text: str) -> str:
    """Normalise Turkish and collapse carrier names onto their IATA codes.

    `Türk Hava Yolları'nın yeni hattı` and `THY yeni hat açıyor` both come out
    naming `tk`, which is what lets them meet at all.
    """
    normalized = tr_normalize(text)
    if not normalized:
        return ""
    padded = f" {normalized} "
    for alias, code in _ALIAS_BY_LENGTH:
        if alias in normalized:
            padded = padded.replace(f" {alias} ", f" {code.lower()} ")
    return padded.strip()


#: Words that appear in aviation headlines regardless of WHICH story it is.
#: Two headlines sharing only these share nothing. Stemmed to STEM_LEN on the
#: way into GENERIC_TOKENS, so the entries here are written out in full.
_BOILERPLATE = (
    # Turkish
    "yeni", "acikladi", "duyurdu", "basladi", "basliyor", "aciliyor", "oldu",
    "icin", "ile", "sonra", "kadar", "varan", "gore", "yapti", "verdi",
    "aldi", "kararı", "karari", "hakkinda", "uzerine", "tarafindan", "olarak",
    "kampanya", "kampanyasi", "indirim", "indirimi", "firsat", "firsati",
    "ucus", "ucuslar", "sefer", "seferler", "bilet", "biletleri", "hat",
    "hatti", "hatlari", "yolcu", "ucak", "havayolu", "havayollari",
    # English
    "new", "adds", "add", "opens", "open", "plans", "plan", "announces",
    "announced", "announcement", "says", "said", "reports", "reported",
    "after", "over", "with", "from", "into", "will", "have", "has",
    "flight", "flights", "route", "routes", "airline", "airlines", "airport",
    "service", "services", "launch", "launches", "start", "starts",
)
GENERIC_TOKENS: frozenset[str] = frozenset(
    token for word in _BOILERPLATE for token in stem_tokens(word)
)


def subject_tokens(text: str) -> set[str]:
    """Stemmed tokens of canonicalised text -- what two titles are compared on."""
    return stem_tokens(canonicalize(text))


def distinctive_tokens(text: str) -> set[str]:
    """Tokens that could tell two stories apart: not boilerplate, not a bare
    carrier code (the code is the subject, and the subject is tested
    separately)."""
    tokens = subject_tokens(text)
    codes = {code.lower() for _alias, code in _ALIAS_BY_LENGTH}
    return {t for t in tokens if t not in GENERIC_TOKENS and t not in codes}


def _tier_for_trust_weight(weight: float) -> str:
    """Bucket a bare trust_weight into a tier, for sources with none declared.

    Every source app/ingest/sources_seed.py seeds now declares a real tier
    (SourceSeed.tier), reconciled onto Source.tier by ensure_seeded(). This
    bucketing only fires for a row seeded before that field existed and not
    yet reconciled, or a source added by hand outside the seed list -- it is
    the fallback, not the primary path. See tier_for_source below.
    """
    if weight >= 0.90:
        return "regulator"
    if weight >= 0.75:
        return "agency"
    if weight >= 0.50:
        return "trade"
    return "aggregator"


def tier_for_source(source) -> str:
    """The declared tier when there is one; the trust_weight bucket otherwise."""
    if source is None:
        return "trade"
    if source.tier:
        return source.tier
    return _tier_for_trust_weight(source.trust_weight)


def entity_codes(article) -> frozenset[str]:
    """Subject entities for clustering, reusing v1's heuristic extraction
    rather than spending a model call before we even know if this article
    clears the gate."""
    codes: set[str] = set()
    for link in article.entity_links:
        entity = link.entity
        if entity is None:
            continue
        if entity.code:
            codes.add(entity.code.upper())
        elif entity.entity_type == "country" and entity.name:
            codes.add(entity.name.upper())
    return frozenset(codes)


@dataclass(frozen=True)
class EventCandidate:
    """One article, reduced to what clustering needs."""

    article_id: object
    title: str
    #: Codes and names from the gazetteer: airlines, airports, countries.
    entities: frozenset[str] = field(default_factory=frozenset)
    #: Source reliability tier, used to pick the cluster's primary article.
    tier: str = "trade"
    #: Publication time, breaking ties on tier.
    published_at: object = None

    @property
    def tokens(self) -> set[str]:
        return subject_tokens(self.title)


def entity_overlap(left: EventCandidate, right: EventCandidate) -> frozenset[str]:
    """Subject entities the two articles agree on."""
    return frozenset(e.upper() for e in left.entities) & frozenset(
        e.upper() for e in right.entities
    )


def title_similarity(left: EventCandidate, right: EventCandidate) -> float:
    return jaccard(left.tokens, right.tokens)


def distinctive_overlap(left: EventCandidate, right: EventCandidate) -> set[str]:
    """Shared tokens that actually identify a story: a city, a number, a route.

    Two unrelated Pegasus campaigns share the carrier and every word a campaign
    announcement uses, and nothing here.
    """
    return distinctive_tokens(left.title) & distinctive_tokens(right.title)


def same_event(left: EventCandidate, right: EventCandidate) -> bool:
    """Do these two articles report the same thing?

    Both halves must hold below the certainty line: similar wording *and* a
    shared subject. Two Pegasus campaigns a month apart share their vocabulary
    and their airline, which is why similarity is still required on top of the
    entity match -- and two unrelated Turkish Airlines stories share the
    carrier, which is why entities are not enough on their own.
    """
    similarity = title_similarity(left, right)
    if similarity >= TITLE_SIMILARITY_CERTAIN:
        return True
    if similarity < TITLE_SIMILARITY_MIN:
        return False
    # Same subject AND a shared distinguishing detail. Either alone
    # over-merges: two Turkish Airlines stories share the carrier, and two
    # campaign announcements share their entire vocabulary.
    return bool(entity_overlap(left, right)) and bool(distinctive_overlap(left, right))


def needs_adjudication(left: EventCandidate, right: EventCandidate) -> bool:
    """A pair that is similar enough to be suspicious and has nothing to confirm it.

    These are the only pairs worth spending a model call on. Everything else is
    decided deterministically, which keeps the adjudication budget proportional
    to genuine ambiguity rather than to feed volume.
    """
    similarity = title_similarity(left, right)
    if not (TITLE_SIMILARITY_MIN <= similarity < TITLE_SIMILARITY_CERTAIN):
        return False
    # Shares a distinguishing detail but no known subject -- typically an
    # airport or regulator story where the gazetteer recognised nothing. A
    # human would look; so should a cheap model call.
    return bool(distinctive_overlap(left, right)) and not entity_overlap(left, right)


#: Tier ranking for choosing an event's primary article. Mirrors the confidence
#: module's ladder; the primary is the most reliable telling, and its text is
#: what gets classified and shown.
_TIER_RANK = {"official": 0, "regulator": 1, "agency": 2, "trade": 3, "aggregator": 4}


def pick_primary(candidates: list[EventCandidate]) -> EventCandidate:
    """Highest source tier wins; earliest publication breaks the tie.

    Earliest rather than latest deliberately: the first telling is the one the
    others are echoing, and it is the link a reader should be sent to.
    """
    if not candidates:
        raise ValueError("an event needs at least one article")
    return min(
        candidates,
        key=lambda c: (
            _TIER_RANK.get(c.tier, len(_TIER_RANK)),
            c.published_at or "9999",
        ),
    )


def cluster(candidates: list[EventCandidate]) -> list[list[EventCandidate]]:
    """Group candidates into events by transitive `same_event` closure.

    Quadratic, and deliberately so at this scale: the window is a few hundred
    articles and the comparison is set intersection over short token sets. The
    MinHash/LSH index in pipeline/dedup.py exists for the whole-corpus case;
    reaching for it here would add a moving part for no measurable gain.
    """
    clusters: list[list[EventCandidate]] = []
    for candidate in candidates:
        for existing in clusters:
            if any(same_event(candidate, member) for member in existing):
                existing.append(candidate)
                break
        else:
            clusters.append([candidate])
    return clusters
