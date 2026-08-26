"""Turkish country names resolve to the same canonical country as their
English form.

Before this table existed, only English country names were reachable through
the gazetteer -- "turkiye", "almanya", "rusya", "ukrayna", "italya" and
"fransa" all resolved to nothing. Twelve Turkish feeds run through this
gazetteer, so a Turkish article naming its own country's neighbours produced
no country entity at all. This is how a Dubai drone story landed in Iran and
a Russian airbase strike in China -- the correct country wasn't unreachable by
mistake, it was unreachable by construction.
"""
import pytest

from app.llm.gazetteer import COUNTRY_ALIASES, _TURKISH_COUNTRY_NAMES, fold_for_match
from app.llm.heuristic import HeuristicProvider
from app.taxonomy import COUNTRY_TO_REGION


def test_every_turkish_country_name_resolves_to_a_real_region():
    """Every target must be a real key in COUNTRY_TO_REGION, or the alias
    resolves to a country the rest of the pipeline cannot place on the map."""
    missing = {en for en in _TURKISH_COUNTRY_NAMES.values() if en not in COUNTRY_TO_REGION}
    assert not missing, f"Turkish aliases point at unknown countries: {sorted(missing)}"


@pytest.mark.parametrize(
    "turkish,english",
    [
        ("Türkiye", "turkey"), ("Almanya", "germany"), ("Rusya", "russia"),
        ("Ukrayna", "ukraine"), ("İtalya", "italy"), ("Fransa", "france"),
        ("İngiltere", "united kingdom"), ("İspanya", "spain"),
        ("Suudi Arabistan", "saudi arabia"),
        ("Birleşik Arap Emirlikleri", "united arab emirates"),
    ],
)
def test_turkish_name_and_english_name_resolve_to_the_same_country(turkish, english):
    assert COUNTRY_ALIASES[fold_for_match(turkish)] == COUNTRY_ALIASES[fold_for_match(english)]


def test_diacritics_are_optional():
    """Written without diacritics, as plenty of Turkish copy is."""
    assert COUNTRY_ALIASES[fold_for_match("Turkiye")] == "turkey"
    assert COUNTRY_ALIASES[fold_for_match("Italya")] == "italy"


@pytest.mark.parametrize("word", ["mali", "cad", "gine"])
def test_ordinary_turkish_words_are_not_treated_as_countries(word):
    """"Mali" is the common Turkish adjective for financial/fiscal ("mali
    yıl", "mali tablo") -- every finance article would otherwise resolve to
    the country Mali. Excluded on the same caution the English table already
    applies to Georgia, Jordan, Chad, Guinea, Niger and Mali."""
    assert COUNTRY_ALIASES.get(word) is None


@pytest.mark.parametrize(
    "title,expected_country",
    [
        # Real Risk Radar rows the country field was empty for, despite the
        # country being spelled out plainly in the headline.
        ("Macaristan'da Gripen düştü", "Hungary"),
        ("İTALYA'DA FIRTINA DEHŞETİ", "Italy"),
        ("Kuzey İtalya'da Şiddetli Fırtına: Uçaklar Savruldu", "Italy"),
    ],
)
async def test_real_audit_cases_now_resolve_a_country(title, expected_country):
    entities = await HeuristicProvider().extract_entities(title, "")
    countries = [e.name for e in entities if e.entity_type == "country"]
    assert expected_country in countries, f"{title!r} -> {countries}"
