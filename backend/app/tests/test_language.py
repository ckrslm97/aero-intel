"""Language detection, against the real headlines that got through.

Every string below except the synthetic ones is a headline the pipeline
actually published to a Turkish-language UI, untranslated, because nothing in
the codebase knew what language anything was in.
"""
import pytest

from app.pipeline.language import (
    MIN_CHARS,
    SUPPORTED,
    detect,
    resolve,
)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("THY Uçağında Yolcu Hayatını Kaybetti", "tr"),
        ("Pegasus'ta 6 hatta yüzde 50'ye varan indirim kampanyası başladı", "tr"),
        ("Airbus'ta Süresiz Grev Kararı!", "tr"),
        ("Air passenger demand falls in June, IATA says", "en"),
        ("Did we just get struck by lightning?", "en"),
    ],
)
def test_supported_languages_are_recognised(title, expected):
    assert resolve(title).language == expected
    assert resolve(title).is_supported


@pytest.mark.parametrize(
    "title,expected",
    [
        # aeroTELEGRAPH, 32 of 200 sampled articles.
        (
            "Warum Premium-Reisende ihren Aperitif in den USA künftig früher abgeben müssen",
            "de",
        ),
        # Aviacionline, 24 of 200.
        ("Hallan tercer dron con explosivos en el aeropuerto de Leipzig", "es"),
    ],
)
def test_foreign_articles_are_rejected_with_a_reason(title, expected):
    verdict = resolve(title)
    assert verdict.language == expected
    assert not verdict.is_supported
    assert verdict.rejection_reason == f"language:{expected}"


def test_supported_set_is_exactly_english_and_turkish():
    """The owner's instruction was explicit: English and Turkish, nothing else."""
    assert SUPPORTED == {"en", "tr"}


# --- declaration vs detection ------------------------------------------------


def test_short_fragment_falls_back_to_the_source_declaration():
    """"Pegasus BolBol" is two brand words. A detector will name a language for
    it -- Estonian, as it happens -- and be wrong. The feed's own declaration is
    the better answer here, and this is why detection does not simply win."""
    verdict = resolve("Pegasus BolBol", declared="tr")
    assert verdict.language == "tr"
    assert verdict.basis == "declared"


def test_confident_detection_overrules_a_wrong_declaration():
    """The mixed-language feed case: a Belgian outlet declared as English that
    publishes the occasional French item."""
    verdict = resolve(
        "Brussels Airlines annonce de nouvelles destinations pour la saison",
        declared="en",
    )
    assert verdict.language == "fr"
    assert verdict.basis == "detected_over_declared"
    assert not verdict.is_supported


def test_agreement_reports_the_declaration_as_the_basis():
    verdict = resolve("Air passenger demand falls in June, IATA says", declared="en")
    assert (verdict.language, verdict.basis) == ("en", "declared")


def test_unknowable_without_a_declaration_is_rejected_not_guessed():
    """Not knowing means not publishing -- the pipeline's standing rule."""
    verdict = resolve("TK1", declared=None)
    assert verdict.language is None
    assert verdict.basis == "unknown"
    assert not verdict.is_supported
    assert verdict.rejection_reason == "language:unknown"


def test_text_below_the_minimum_length_yields_no_opinion():
    assert len("TK 1234") < MIN_CHARS
    assert detect("TK 1234") == (None, 0.0)


def test_body_is_used_when_the_headline_is_thin():
    """Google News radars deliver headlines only; where a body exists it is far
    more reliable than six words of title."""
    verdict = resolve(
        "Update",
        "Türk Hava Yolları, kış tarifesinde Avrupa'ya ek sefer koyduğunu duyurdu. "
        "Kampanya kapsamında bilet fiyatlarında indirim yapılacak.",
    )
    assert verdict.language == "tr"


def test_a_long_body_does_not_slow_the_classifier_down():
    """The sample is bounded; a 3,000-word body buys nothing over 600 chars."""
    body = "Turkish Airlines announced new routes. " * 400
    assert resolve("Route news", body).language == "en"
