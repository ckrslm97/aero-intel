"""The Turkish labels are canonical here and rendered in four places -- the
newsletter, the PDF, the newspaper sections and the frontend. Previously each of
those kept its own copy and drift was silent; these tests are the other half of
that fix, catching a slug added to the taxonomy without a label to render it.
"""
from app.email.render import SECTION_LABELS
from app.services.recommendations import CATEGORY_LABELS_TR as RECOMMENDATION_CATEGORY_LABELS
from app.taxonomy import (
    CATEGORY_LABELS_TR,
    CATEGORY_SLUGS,
    COUNTRY_TO_REGION,
    REGION_LABELS_TR,
)


def test_every_category_has_a_turkish_label():
    missing = set(CATEGORY_SLUGS) - set(CATEGORY_LABELS_TR)
    assert not missing, f"categories without a Turkish label: {sorted(missing)}"


def test_no_label_for_a_category_that_does_not_exist():
    # The other direction: a renamed slug leaves an orphan label that renders
    # nowhere and hides the fact that the real slug lost its name.
    orphans = set(CATEGORY_LABELS_TR) - set(CATEGORY_SLUGS)
    assert not orphans, f"labels for unknown categories: {sorted(orphans)}"


def test_every_region_the_pipeline_can_emit_has_a_turkish_label():
    missing = set(COUNTRY_TO_REGION.values()) - set(REGION_LABELS_TR)
    assert not missing, f"regions without a Turkish label: {sorted(missing)}"


def test_labels_are_not_blank():
    for slug, label in {**CATEGORY_LABELS_TR, **REGION_LABELS_TR}.items():
        assert label.strip(), f"{slug} has an empty label"


def test_consumers_read_the_canonical_labels():
    """Guards the consolidation itself: if someone reintroduces a local copy,
    these stop agreeing and the test says so before the newsletter and the web
    disagree in front of a reader."""
    assert RECOMMENDATION_CATEGORY_LABELS is CATEGORY_LABELS_TR

    # The newsletter adds the lead slot on top of the categories; everything
    # else it renders is a category label straight from the taxonomy.
    assert SECTION_LABELS["top_story"] == "Öne Çıkanlar"
    for slug, label in CATEGORY_LABELS_TR.items():
        assert SECTION_LABELS[slug] == label, slug
