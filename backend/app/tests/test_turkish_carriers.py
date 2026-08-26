"""The home carrier's Turkish name resolves to its IATA code.

Twelve Turkish feeds run through the gazetteer, and the only Turkish-language
carrier name in it was "turkish airlines" -- which is English. A Turkish
article about THY produced no TK entity at all, so the airline filter, the
campaign attribution and the BİZ page each silently lost every Turkish source
while appearing to work.
"""
import pytest

from app.llm.gazetteer import AIRLINE_ALIASES, fold_for_match
from app.llm.heuristic import HeuristicProvider


@pytest.mark.parametrize(
    "title,code",
    [
        ("Türk Hava Yolları kış tarifesini açıkladı", "TK"),
        # Agglutination: the case ending is attached after an apostrophe.
        ("THY'nin Avrupa seferlerinde kapasite artışı", "TK"),
        ("THY, Latin Amerika'ya yeni hat açıyor", "TK"),
        # Written without diacritics, as plenty of Turkish copy is.
        ("Turk Hava Yollari yeni ucak siparisi verdi", "TK"),
        ("Turkish Airlines announces winter schedule", "TK"),
        ("Pegasus'ta 6 hatta yüzde 50'ye varan indirim kampanyası başladı", "PC"),
        ("Pegasus Hava Yolları filosunu büyütüyor", "PC"),
        ("AnadoluJet yeni hat açıyor", "VF"),
        ("AJet kış tarifesini duyurdu", "VF"),
    ],
)
async def test_turkish_carrier_names_extract_to_iata_codes(title, code):
    entities = await HeuristicProvider().extract_entities(title, "")
    codes = {e.code for e in entities if e.entity_type == "airline"}
    assert code in codes, f"{title!r} produced {codes or 'no airline'}"


def test_aliases_are_stored_folded_so_diacritics_are_optional():
    """Aliases are written with diacritics for readability and folded on the way
    in, so "Türk" and "Turk" reach the same key."""
    assert AIRLINE_ALIASES[fold_for_match("Türk Hava Yolları")] == ("Turkish Airlines", "TK")
    assert AIRLINE_ALIASES["turk hava yollari"] == ("Turkish Airlines", "TK")


def test_rival_carriers_still_resolve():
    """The Turkish additions must not have shadowed anything."""
    for alias, code in [
        ("emirates", "EK"),
        ("qatar airways", "QR"),
        ("lufthansa", "LH"),
        ("british airways", "BA"),
    ]:
        assert AIRLINE_ALIASES[alias][1] == code
