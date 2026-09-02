"""Keyword hygiene for app/taxonomy.py.

The scorer matches keywords against normalize_text(article), which strips every
character outside [a-z0-9\\s]. A keyword containing anything else is therefore
dead on arrival -- it compiles into a pattern the normalized text can never
satisfy, scores zero forever, and looks perfectly reasonable in review.

Three of them shipped that way and stayed: "add-on" under ancillary and
"full-year" under finance (twice), unmatchable for as long as they were in the
list. These tests are the reason a fourth cannot.
"""
from app.pipeline.hashing import normalize_text
from app.taxonomy import (
    CATEGORIES,
    CATEGORY_SLUGS,
    RM_SHIFT_FROM_CATEGORIES,
    RM_SHIFT_KEYWORDS,
    RM_SHIFT_MIN_SCORE,
    RM_SHIFT_TARGET,
)


def _all_keywords() -> list[tuple[str, str]]:
    """(where, keyword) for every keyword the categorizer scores."""
    pairs: list[tuple[str, str]] = []
    for category in CATEGORIES:
        pairs += [(category.slug, kw) for kw in category.keywords]
        for sub in category.subcategories:
            pairs += [(f"{category.slug}/{sub.slug}", kw) for kw in sub.keywords]
    pairs += [("RM_SHIFT_KEYWORDS", kw) for kw in RM_SHIFT_KEYWORDS]
    return pairs


def test_every_keyword_survives_normalization():
    dead = [
        (where, kw, normalize_text(kw))
        for where, kw in _all_keywords()
        if normalize_text(kw) != kw.strip()
    ]
    assert not dead, (
        "these keywords cannot match normalized article text -- write them the "
        f"way normalize_text leaves them: {dead}"
    )


def test_no_keyword_is_blank():
    for where, kw in _all_keywords():
        assert kw.strip(), f"empty keyword in {where}"


def test_subcategory_slugs_are_unique_within_their_category():
    """Two rows with the same slug under one category is not a merge conflict
    the type system catches: SUBCATEGORY_KEYWORDS is a dict, so the second
    silently replaces the first and takes its keywords with it."""
    for category in CATEGORIES:
        slugs = [s.slug for s in category.subcategories]
        assert len(slugs) == len(set(slugs)), f"duplicate subcategory slug in {category.slug}"


def test_rm_shift_rule_is_narrow():
    """The fleet/finance -> revenue_management rule, as a rule rather than as a
    list of words. It must only ever pull from the two categories it names, it
    must not name its own target, and it must require real evidence -- a
    threshold of 0 would move every fleet story on the first stray phrase."""
    assert RM_SHIFT_TARGET == "revenue_management"
    assert set(RM_SHIFT_FROM_CATEGORIES) == {"fleet", "finance"}
    assert RM_SHIFT_TARGET not in RM_SHIFT_FROM_CATEGORIES
    assert set(RM_SHIFT_FROM_CATEGORIES) <= set(CATEGORY_SLUGS)
    assert RM_SHIFT_MIN_SCORE >= 3, "one headline hit is the intended floor"


def test_rm_shift_keywords_are_compounds_not_bare_fleet_words():
    """The rule's whole design is that a plain order, delivery or set of
    results does NOT move. Admitting any of these as a standalone keyword would
    quietly turn the rule into "every fleet story is revenue management"."""
    forbidden = {
        "order", "orders", "delivery", "deliveries", "aircraft", "fleet",
        "profit", "revenue", "earnings", "results", "boeing", "airbus",
    }
    offenders = sorted(forbidden.intersection(RM_SHIFT_KEYWORDS))
    assert not offenders, f"too broad to be a shift signal on its own: {offenders}"
