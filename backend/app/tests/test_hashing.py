from app.pipeline.hashing import content_hash, normalize_text, shingles


def test_normalize_text_strips_punctuation_and_case():
    assert normalize_text("Delta Air Lines: Q3 Earnings!") == "delta air lines q3 earnings"


def test_content_hash_is_stable_for_identical_input():
    a = content_hash("Same headline", "Same body text")
    b = content_hash("Same headline", "Same body text")
    assert a == b


def test_content_hash_ignores_case_and_punctuation():
    a = content_hash("Delta Air Lines Q3 Earnings", "Revenue rose 5%.")
    b = content_hash("delta air lines q3 earnings", "revenue rose 5")
    assert a == b


def test_content_hash_differs_for_different_input():
    a = content_hash("Delta announces new routes", "Delta body")
    b = content_hash("United announces new routes", "United body")
    assert a != b


def test_shingles_short_text_returns_single_shingle():
    assert shingles("Delta Air Lines") == {"delta air lines"}


def test_shingles_overlap_for_near_duplicate_text():
    a = shingles("Delta Air Lines announces new route to Tokyo starting next spring")
    b = shingles("Delta Air Lines announced a new route to Tokyo starting next spring")
    intersection = a & b
    assert len(intersection) > 0
