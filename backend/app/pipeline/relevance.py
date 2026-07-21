"""How much commercial-aviation signal an article carries, scored locally.

Every fetched article used to take the full LLM path -- and most of them are
not what this portal is for. The Google News radars alone return ~100 items a
run, and anything that matches no category keyword lands in the "general"
bucket *after* we have already paid for a classification call. With ingest
running at 250-700 articles/day against a 144-article LLM budget, the backlog
could only grow.

This module answers "is this worth spending the budget on?" with the keyword
tables the taxonomy already defines -- no network, no model, microseconds per
article. Articles below the threshold still get enriched, just entirely on the
local heuristic path: they stay searchable and filterable, and the UI already
labels them honestly as untranslated.

The same score doubles as the ranking signal for "sort by importance".
"""
from dataclasses import dataclass, field

from app.llm.heuristic import _keyword_pattern, _score
from app.pipeline.hashing import normalize_text
from app.taxonomy import CATEGORY_KEYWORDS, GENERAL_CATEGORY

# The focus beats of the portal (see FOCUS_BONUS in edition_service.py, which
# applies the same editorial priority to the front page). A hit here is worth
# more than a hit in, say, safety -- both are aviation, only one is why an RM
# analyst opens this site.
FOCUS_CATEGORIES: dict[str, int] = {
    "revenue_management": 3,
    "network": 2,
    "finance": 2,
    "events": 2,
}

# Words that mark an article as commercially interesting regardless of which
# category it lands in -- a fleet story about ancillary bundles is still an RM
# story. Deliberately narrow: these add signal, they don't define it.
COMMERCIAL_TERMS: tuple[str, ...] = (
    "fare", "fares", "pricing", "price", "yield", "revenue", "ancillary",
    "load factor", "capacity", "demand", "booking", "bookings", "ndc",
    "distribution", "route", "routes", "network", "frequency", "codeshare",
    "joint venture", "alliance", "promotion", "discount", "bundle",
    "unit revenue", "rask", "cask", "rpk", "ask", "hub", "slot", "seat sale",
)

_COMMERCIAL_PATTERN = _keyword_pattern(COMMERCIAL_TERMS)

# Terms that make an article relevant on their own, however short it is.
# Calibrated against 400 production articles: rival campaign stories -- exactly
# what the user asked to track -- are written as terse one-liners ("Qatar
# Airways offers discount to Athens"), so keyword *density* scored them below a
# rambling piece about an airport cat. Presence, not frequency, is the right
# test for these.
DECISIVE_TERMS: tuple[str, ...] = (
    "promotion", "promo", "discount", "sale", "offer", "offers", "campaign",
    "fare", "fares", "pricing", "price", "miles", "avios", "loyalty",
    "frequent flyer", "bonus", "voucher", "companion", "upgrade", "baggage fee",
    "checked bag", "ancillary", "ndc", "codeshare", "joint venture",
    "new route", "route", "capacity", "load factor", "yield", "revenue",
)
_DECISIVE_PATTERN = _keyword_pattern(DECISIVE_TERMS)

# What a decisive term in the TITLE is worth. Enough to clear the default
# threshold on its own -- a headline that says "discount" is about a discount.
DECISIVE_TITLE_BONUS = 6

# The home carrier and the named rivals. A story about any of them is by
# definition what this desk watches, whatever else the keyword tables make of
# it: calibration showed "Turkish Airlines Targets Lima As Latin America
# Expansion Continues" scoring below the gate purely for being briefly worded.
WATCHED_AIRLINES: tuple[str, ...] = (
    "turkish airlines", "türk hava yolları", "turkish airlines'",
    "ajet", "anadolujet", "pegasus airlines",
    "emirates", "qatar airways", "etihad", "lufthansa", "air france",
    "klm", "british airways",
)
_WATCHED_PATTERN = _keyword_pattern(WATCHED_AIRLINES)
WATCHED_AIRLINE_BONUS = 6


# When the local scorer may overrule the model's category. Both conditions
# must hold, and both were calibrated on the exact production sample that
# showed the problem:
#
#   "SR Technics signs engine maintenance agreement"  fleet 3, RM 1
#   "Embraer receives E2 orders at Farnborough 2026"  fleet 7, RM 1
#   "Premium Economy Is Quietly Becoming Best Value"  fleet 2, RM 2  <- leave alone
#
# A margin alone would fire on the third (a genuinely RM story that happens to
# name an aircraft); an evidence floor alone would fire wherever the model is
# merely reading between the lines. Together they catch the first two and only
# those.
OVERRIDE_MARGIN = 2
MIN_OVERRIDE_EVIDENCE = 3


@dataclass(frozen=True)
class Relevance:
    score: int
    category: str
    """The best-scoring category from the local pass. Not authoritative -- the
    LLM re-decides for articles that clear the gate -- but it is what a skipped
    article is filed under."""

    raw_by_category: dict[str, int] = field(default_factory=dict)
    """Unweighted keyword score per category, kept so the LLM's choice can be
    sanity-checked against the evidence (see better_category_than)."""

    @property
    def is_general(self) -> bool:
        return self.category == GENERAL_CATEGORY

    def better_category_than(self, chosen: str) -> str | None:
        """The category the keywords point to, when the model's pick is clearly
        contradicted -- otherwise None.

        The model is trusted by default. An override needs a category that
        both carries real evidence of its own and clearly beats the model's
        pick -- see the constants for the production cases that set the bar.
        """
        if not self.raw_by_category:
            return None

        chosen_score = self.raw_by_category.get(chosen, 0)
        ranked = sorted(self.raw_by_category.items(), key=lambda kv: -kv[1])
        best, best_score = ranked[0]
        if best == chosen:
            return None
        # An outright tie for first place is not evidence of anything.
        if len(ranked) > 1 and ranked[1][1] == best_score and ranked[1][0] != chosen:
            return None
        if best_score < MIN_OVERRIDE_EVIDENCE:
            return None
        if best_score - chosen_score < OVERRIDE_MARGIN:
            return None
        return best


# Below this, `content` is a stub (an aggregator echoing the headline plus a
# publisher credit) rather than an article body. Measured on production: 804 of
# 997 waiting articles have under 120 characters of body, because the Google
# News radars deliver headlines only. Frequency-based scoring is meaningless on
# those, so the title has to carry the decision alone.
_STUB_BODY_CHARS = 120
# Compensates for the missing body when there is none to count.
HEADLINE_ONLY_BONUS = 3


def score_article(title: str, content: str) -> Relevance:
    """Local relevance score. Higher = more commercial-aviation signal."""
    title_text = normalize_text(title)
    body_text = normalize_text(content)
    headline_only = len(content or "") < _STUB_BODY_CHARS

    best_category = GENERAL_CATEGORY
    best_score = 0
    raw_by_category: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        raw = _score(_keyword_pattern(tuple(keywords)), title_text, body_text)
        raw_by_category[category] = raw
        weighted = raw * FOCUS_CATEGORIES.get(category, 1)
        if weighted > best_score:
            best_score = weighted
            best_category = category

    commercial = _score(_COMMERCIAL_PATTERN, title_text, body_text)
    decisive = DECISIVE_TITLE_BONUS if _DECISIVE_PATTERN.search(title_text) else 0
    watched = WATCHED_AIRLINE_BONUS if _WATCHED_PATTERN.search(title_text) else 0
    # A headline-only item scored on the same scale as a full article would be
    # gated out for the length of its body, not for what it is about. Gated on
    # a *commercial* hit, not merely any category hit: "Airport cat adopted by
    # ground crew" matches the airport table and would otherwise ride the
    # stub bonus straight through the gate.
    stub = HEADLINE_ONLY_BONUS if headline_only and commercial > 0 else 0
    return Relevance(
        score=best_score + commercial + decisive + watched + stub,
        category=best_category,
        raw_by_category=raw_by_category,
    )
