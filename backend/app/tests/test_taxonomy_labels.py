"""The Turkish labels are canonical here and rendered in four places -- the
newsletter, the PDF, the newspaper sections and the frontend. Previously each of
those kept its own copy and drift was silent; these tests are the other half of
that fix, catching a slug added to the taxonomy without a label to render it.
"""
from datetime import datetime, timezone

from app.api.v1 import kpis as kpis_api
from app.email.render import SECTION_LABELS
from app.ingest.historical_seed import ESTIMATE_YEAR, FORECAST_YEAR, year_kind
from app.services.kpi_service import PUBLISHED_ESTIMATE_KEYS
from app.services.recommendations import CATEGORY_LABELS_TR as RECOMMENDATION_CATEGORY_LABELS
from app.taxonomy import (
    CATEGORY_LABELS_TR,
    CATEGORY_SLUGS,
    COUNTRY_TO_REGION,
    PERIOD_KIND_LABELS_TR,
    PERIOD_KINDS,
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


def test_every_period_kind_the_seed_can_emit_has_one_turkish_name():
    """`year_kind` decides WHAT a yearly figure is; this map decides what that
    is CALLED, and both halves have to cover the same three values.

    The KPI detail page renders the name server-side and Kokpit's outlook tile
    renders it client-side out of taxonomy.gen.ts. They used to hold separate
    dictionaries: an IATA 2025 column read "ön gerçekleşme" on one and
    "tahmini gerçekleşme" on the other -- the same row, two words.
    """
    emitted = {
        year_kind(FORECAST_YEAR + 1),
        year_kind(FORECAST_YEAR),
        year_kind(ESTIMATE_YEAR),
        year_kind(ESTIMATE_YEAR - 1),
    }
    assert emitted == set(PERIOD_KINDS)
    assert set(PERIOD_KIND_LABELS_TR) == set(PERIOD_KINDS)
    for kind, label in PERIOD_KIND_LABELS_TR.items():
        assert label.strip(), f"{kind} has an empty label"


def test_the_kpi_period_label_reads_the_canonical_names():
    """The consolidation itself: /kpi/<metric>'s period label is built from the
    shared map, not from a second copy in the API module."""
    assert kpis_api.PERIOD_KIND_LABELS_TR is PERIOD_KIND_LABELS_TR

    as_of = datetime(ESTIMATE_YEAR, 12, 31, tzinfo=timezone.utc)
    metric = next(iter(PUBLISHED_ESTIMATE_KEYS))
    assert kpis_api.period_label_for(metric, as_of) == (
        f"{ESTIMATE_YEAR} · {PERIOD_KIND_LABELS_TR['estimate']}"
    )
    # A live metric is not a period at all, and still says so.
    assert kpis_api.period_label_for("fx_usd_try", as_of) == kpis_api.LIVE_PERIOD_LABEL_TR
