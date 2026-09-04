"""Event clustering.

The measured problem: `Jin Air, Air Busan and Air Seoul to merge` was filed
under `finance/equity` from its English source and `general` from its German
one -- one event, two classifications, two rows. Roughly 12% of a 200-article
sample was unmerged duplicates.
"""
import pytest

from app.pipeline.clustering import (
    EventCandidate,
    canonicalize,
    cluster,
    distinctive_overlap,
    needs_adjudication,
    pick_primary,
    same_event,
    title_similarity,
)


def _c(id_, title, entities=(), tier="trade", published_at=None):
    return EventCandidate(id_, title, frozenset(entities), tier, published_at)


# --- canonicalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Türk Hava Yolları yeni hat açıyor",
        "THY yeni hat açıyor",
        "THY'nin yeni hattı",
        "Turkish Airlines opens a new route",
    ],
)
def test_every_form_of_the_carrier_name_collapses_to_its_code(title):
    """`THY`, `Türk Hava Yolları` and `Turkish Airlines` are one carrier. Until
    the gazetteer learned the Turkish names, none of them met."""
    assert "tk" in canonicalize(title).split()


def test_turkish_case_endings_do_not_survive_canonicalisation():
    assert canonicalize("THY'nin") == canonicalize("THY")


# --- the decision -------------------------------------------------------------


def test_two_tellings_of_one_event_cluster_across_languages():
    turkish = _c(1, "Türk Hava Yolları Lima hattını açıyor", {"TK", "LIM"})
    english = _c(2, "Turkish Airlines launches Lima route", {"TK", "LIM"})
    assert same_event(turkish, english)


def test_two_turkish_tellings_cluster_despite_different_suffixes():
    """Turkish writes the same idea with different endings and a different
    verb, so the union grows while the intersection does not."""
    a = _c(1, "THY'nin Lima hattı 2027'de açılıyor", {"TK", "LIM"})
    b = _c(2, "Türk Hava Yolları Lima seferlerine başlıyor", {"TK", "LIM"})
    assert title_similarity(a, b) < 0.30, "wording similarity really is this low"
    assert same_event(a, b), "and they are still plainly the same event"


def test_a_jaccard_threshold_could_not_have_separated_these():
    """The measurement that killed the threshold approach: two *different*
    Pegasus campaigns score HIGHER on wording similarity than two tellings of
    one Turkish Airlines route launch. No threshold splits that."""
    same_a = _c(1, "THY'nin Lima hattı 2027'de açılıyor", {"TK", "LIM"})
    same_b = _c(2, "Türk Hava Yolları Lima seferlerine başlıyor", {"TK", "LIM"})
    different_a = _c(3, "Pegasus'ta 6 hatta indirim kampanyası başladı", {"PC"})
    different_b = _c(4, "Pegasus yeni kampanya duyurdu, biletlerde indirim", {"PC"})

    assert title_similarity(different_a, different_b) > title_similarity(same_a, same_b)
    assert same_event(same_a, same_b)
    assert not same_event(different_a, different_b)


def test_sharing_only_the_carrier_is_not_the_same_event():
    """Every Turkish Airlines story shares the carrier."""
    route = _c(1, "THY Lima hattını açıyor", {"TK", "LIM"})
    order = _c(2, "THY yeni uçak siparişi verdi", {"TK"})
    assert not same_event(route, order)


def test_sharing_only_boilerplate_is_not_the_same_event():
    """Two campaign announcements share their entire vocabulary."""
    a = _c(1, "Pegasus yeni kampanya başlattı", {"PC"})
    b = _c(2, "Pegasus yeni kampanya duyurdu", {"PC"})
    assert distinctive_overlap(a, b) == set()
    assert not same_event(a, b)


def test_near_identical_titles_cluster_without_a_known_entity():
    """Airport and regulator news often names nothing the gazetteer knows."""
    a = _c(1, "EASA issues airworthiness directive for A320 fuel pumps")
    b = _c(2, "EASA issues airworthiness directive covering A320 fuel pumps")
    assert same_event(a, b)


# --- adjudication --------------------------------------------------------------


def test_a_suspicious_pair_with_nothing_to_confirm_it_is_flagged():
    """Shares a distinguishing detail, names no known subject. A human would
    look; so should a cheap model call. These are the only pairs worth one."""
    a = _c(1, "Schiphol caps departing passengers for the winter season")
    b = _c(2, "Amsterdam airport limits winter departing passenger numbers")
    assert needs_adjudication(a, b)


def test_a_confidently_decided_pair_is_not_sent_for_adjudication():
    a = _c(1, "Türk Hava Yolları Lima hattını açıyor", {"TK", "LIM"})
    b = _c(2, "Turkish Airlines launches Lima route", {"TK", "LIM"})
    assert same_event(a, b)
    assert not needs_adjudication(a, b)


# --- primary source ------------------------------------------------------------


def test_the_most_reliable_telling_becomes_the_primary():
    """The primary is what gets classified and what "Kaynağa git" opens."""
    members = [
        _c(1, "THY Lima hattını açıyor", {"TK"}, tier="aggregator", published_at="2026-08-01"),
        _c(2, "Turkish Airlines announces Lima", {"TK"}, tier="official", published_at="2026-08-02"),
        _c(3, "TK to fly Lima", {"TK"}, tier="agency", published_at="2026-08-01"),
    ]
    assert pick_primary(members).article_id == 2


def test_the_earliest_telling_breaks_a_tier_tie():
    """The first report is the one the others are echoing."""
    members = [
        _c(1, "Turkish Airlines announces Lima", {"TK"}, tier="agency", published_at="2026-08-03"),
        _c(2, "Turkish Airlines to serve Lima", {"TK"}, tier="agency", published_at="2026-08-01"),
    ]
    assert pick_primary(members).article_id == 2


def test_an_event_needs_at_least_one_article():
    with pytest.raises(ValueError):
        pick_primary([])


# --- grouping ------------------------------------------------------------------


def test_clustering_groups_an_event_and_leaves_others_alone():
    candidates = [
        _c(1, "Türk Hava Yolları Lima hattını açıyor", {"TK", "LIM"}),
        _c(2, "Turkish Airlines launches Lima route", {"TK", "LIM"}),
        _c(3, "THY'nin Lima seferleri 2027'de başlıyor", {"TK", "LIM"}),
        _c(4, "Pegasus'ta 6 hatta indirim kampanyası başladı", {"PC"}),
        _c(5, "EASA issues airworthiness directive for A320 fuel pumps"),
    ]
    groups = cluster(candidates)
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 1, 3]

    lima = next(g for g in groups if len(g) == 3)
    assert {c.article_id for c in lima} == {1, 2, 3}


def test_a_single_article_is_still_an_event():
    groups = cluster([_c(1, "Pegasus'ta indirim kampanyası", {"PC"})])
    assert len(groups) == 1 and len(groups[0]) == 1


def test_clustering_an_empty_window_is_not_an_error():
    assert cluster([]) == []


# --- the closure is a closure, whatever order the rows arrive in -----------


def _etna_trio():
    """Three tellings of one eruption, chained rather than mutually similar.

    The middle one names both Catania and Sicily and so meets each of the other
    two; the outer two share only the carrier-free boilerplate every eruption
    story uses, and do not meet each other. That is the ordinary shape of real
    coverage, and it is exactly the shape `same_event` is not transitive on.
    """
    catania = _c(
        "a",
        "Etna patlaması Catania Havalimanı'nın kapatılmasına neden oldu",
        entities=("cta",),
    )
    both = _c(
        "b",
        "Etna külleri Catania Havalimanı'nı kapattı, Sicilya genelinde uçuşlar iptal",
        entities=("cta",),
    )
    sicily = _c(
        "c",
        "Mount Etna eruption disrupts travel across Sicily",
        entities=("cta",),
    )
    assert same_event(catania, both)
    assert same_event(both, sicily)
    assert not same_event(catania, sicily)
    return catania, both, sicily


def test_one_event_stays_one_cluster_whatever_order_it_arrives_in():
    """Row order is not a fact about the news.

    `cluster` used to stop at the first cluster a candidate matched, so the
    chain above came out as ONE signal in the order A, B, C and as TWO in the
    order A, C, B -- from the same three articles. Nothing chose that order:
    it was whatever Postgres returned for rows sharing a publication minute,
    which changes with the plan. Now the middle article merges the two ends
    instead of picking one.
    """
    catania, both, sicily = _etna_trio()

    for order in (
        [catania, both, sicily],
        [catania, sicily, both],
        [sicily, catania, both],
        [both, sicily, catania],
    ):
        clusters = cluster(order)
        assert len(clusters) == 1, [tuple(c.article_id for c in g) for g in clusters]
        assert {c.article_id for c in clusters[0]} == {"a", "b", "c"}


def test_merging_does_not_glue_together_events_that_never_met():
    """The negative half. Closure must only ever join clusters through a
    candidate that genuinely matches both -- a merge rule that ran too eagerly
    would collapse a whole day's feed into one signal, which is a worse error
    than the split it fixes."""
    catania, both, sicily = _etna_trio()
    unrelated = _c("d", "Pegasus kış kampanyasında yüzde 40 indirim duyurdu")

    clusters = cluster([catania, unrelated, both, sicily])

    assert len(clusters) == 2
    by_size = sorted(clusters, key=len)
    assert [c.article_id for c in by_size[0]] == ["d"]
    assert {c.article_id for c in by_size[1]} == {"a", "b", "c"}


def test_a_feed_with_nothing_to_merge_keeps_its_original_cluster_order():
    """The merge rule must be invisible when it has nothing to do: a feed of
    unrelated stories comes out in the order it went in, one cluster each."""
    rows = [
        _c("1", "Pegasus kış kampanyasında yüzde 40 indirim duyurdu"),
        _c("2", "Heathrow'da sis nedeniyle yüzlerce uçuş rötar yaptı"),
        _c("3", "IATA küresel yolcu trafiği tahminini yukarı çekti"),
    ]

    clusters = cluster(rows)

    assert [[c.article_id for c in group] for group in clusters] == [["1"], ["2"], ["3"]]
