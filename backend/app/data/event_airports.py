"""Which airports an events-calendar city actually flies through -- curated by
hand, because resolving it automatically does not work.

Why this table is hand-written
------------------------------
`airports.json` carries a `city` field for every airport, so the obvious
implementation is "match the event's city against airport.city". That was
measured against the ten cities the calendar names most often, and it fails on
seven of them:

    city         auto-resolved      what is wrong
    -----------  -----------------  -----------------------------------------
    Paris        LBG                CDG's city is "Paris (Roissy-en-France,
                                    Val-d'Oise)", ORY's is "Paris (Orly,
                                    Val-de-Marne)" -- so the two airports
                                    Paris actually flies through are the two
                                    that do not match, and the business-
                                    aviation field is the only hit
    Milan        --                 MXP is filed under "Ferno (VA)", LIN under
                                    "Segrate (MI)": the municipality, not the
                                    city they serve
    Frankfurt    --                 "Frankfurt am Main"
    Tokyo        HND                NRT is filed under "Narita"
    New York     JFK, LGA           EWR is filed under "Newark"
    London       LHR, LGW, LCY,     YXU is London, Ontario -- a Canadian
                 YXU                regional field in a UK event's list
    Barcelona    BCN, BLA           BLA is Barcelona, Venezuela
    Riyadh       RUH                (the only clean one)
    Munich       MUC                clean
    Lisbon       LIS                clean

Three failure modes, none of them fixable by a better string match: the
dataset stores the *municipality* rather than the metropolitan area
(MXP, LIN, FRA, NRT, EWR), it qualifies some city names with an administrative
district (CDG, ORY), and city names repeat across countries (YXU, BLA). The
last one is the dangerous one -- a missing airport is visibly empty, but a
Venezuelan airport under a Barcelona conference reads exactly like a correct
answer.

`aviation_events.city` is also written in Turkish ("Münih", "Lizbon", "Riyad",
"Şikago"), which no dataset city field will ever match, and roughly a fifth of
the rows are not cities at all ("Çin geneli", "Küresel", "Türkiye ve İslam
dünyası"). Those map to nothing on purpose: an empty list is the honest answer
for a country-wide holiday, and inventing a gateway for it would put a
confident airport code under an event that has none.

`app/data/__init__.py` already states the rule this follows -- the JSON files
are generated and must not be hand-edited, so hand-curated knowledge lives in
code beside them.

Why the fold is duplicated rather than imported
-----------------------------------------------
`app.llm.gazetteer.fold_for_match` does exactly this normalisation, but
importing it here would make `app.data` depend on `app.llm` (which depends on
`app.data`), and it builds a ~3.2k-entry alias table at import time -- 33 ms
and an 800KB JSON parse that the /events endpoint would then pay on every cold
start, which is precisely what `app/data/__init__.py`'s laziness is for. The
fold below is deliberately the same algorithm; `test_event_airports.py` pins
the two against each other so they cannot drift apart silently.
"""
from __future__ import annotations

import re
import unicodedata
from functools import cache

# Same map as app/llm/gazetteer._FOLD_MAP: the diacritics NFKD will not
# decompose. Without "ı"/"İ" here, "Şanlıurfa" folds to "sanl urfa".
_FOLD_MAP = str.maketrans(
    {"ı": "i", "İ": "i", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
     "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
     "ß": "ss", "þ": "th", "Þ": "TH", "ð": "d", "Ð": "D"}
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def fold_city(text: str) -> str:
    """Lowercase, strip diacritics, reduce to `[a-z0-9 ]` tokens.

    Mirrors `app.llm.gazetteer.fold_for_match`. Punctuation becomes a space
    rather than nothing, so "Aichi-Nagoya" and "Adare Manor (Limerick)" fold to
    the same shape a human would type them in.
    """
    text = text.translate(_FOLD_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _WHITESPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", text.lower())).strip()


# Folded city name -> the IATA codes that city's traffic actually uses.
#
# Turkish and English spellings both appear as keys because the seed writes the
# city in Turkish while every other caller (and every reader of this file)
# thinks in English. Both must resolve identically -- a lookup that works for
# "Munich" and not for "Münih" is a lookup that works everywhere except in
# production.
#
# Codes are ordered by how much of the city's traffic they carry, and every one
# of them is asserted to exist in airports.json by the test suite: a typo'd
# code would otherwise pass silently and render as a real airport.
#
# The list is what a passenger flying *to the event* would book, not every
# field inside the municipal boundary. Farnborough has its own airport (FAB),
# but it is a business-aviation field that the bundled scheduled-service cut
# does not even contain, and the airshow's visitors land at Heathrow and
# Gatwick -- which is what the event's own demand line says.
CITY_AIRPORTS: dict[str, tuple[str, ...]] = {
    # --- Europe ---------------------------------------------------------
    "amsterdam": ("AMS",),
    "barselona": ("BCN",),
    "barcelona": ("BCN",),
    "belgrad": ("BEG",),
    "belgrade": ("BEG",),
    "berlin": ("BER",),
    "budapeste": ("BUD",),
    "budapest": ("BUD",),
    "burgas": ("BOJ",),
    # WEF's delegates fly to Zurich and drive the last two hours; Davos itself
    # has no airport, and the traffic is unmistakably ZRH's.
    "davos": ("ZRH",),
    "edinburgh": ("EDI",),
    # See the note above: FAB is not in the scheduled-service dataset and is
    # not where the airshow's 80k visitors arrive.
    "farnborough": ("LHR", "LGW"),
    "frankfurt": ("FRA",),
    "hamburg": ("HAM",),
    "hannover": ("HAJ",),
    "hanover": ("HAJ",),
    "lizbon": ("LIS",),
    "lisbon": ("LIS",),
    "londra": ("LHR", "LGW", "STN", "LTN", "LCY"),
    "london": ("LHR", "LGW", "STN", "LTN", "LCY"),
    "madrid": ("MAD",),
    "milano": ("MXP", "LIN", "BGY"),
    "milan": ("MXP", "LIN", "BGY"),
    "munih": ("MUC",),
    "munich": ("MUC",),
    "paris": ("CDG", "ORY"),
    # The Paris Air Show is at Le Bourget, but nobody flies into Le Bourget for
    # it: LBG first because it is the venue, then the two fields the visitors
    # actually land at.
    "paris le bourget": ("LBG", "CDG", "ORY"),
    # Glastonbury. Pilton is a Somerset village; Bristol is its airport.
    "pilton": ("BRS",),
    "viyana": ("VIE",),
    "vienna": ("VIE",),
    # Ryder Cup 2027. Adare is in County Limerick; Shannon is the gateway.
    "adare manor limerick": ("SNN",),
    "adare manor": ("SNN",),
    "limerick": ("SNN",),
    # --- Middle East ----------------------------------------------------
    "antalya": ("AYT",),
    "doha": ("DOH",),
    "dubai": ("DXB", "DWC"),
    "istanbul": ("IST", "SAW"),
    # Hajj. Mecca has no airport of its own: pilgrims arrive at Jeddah, and
    # Medina carries the rest of the same journey.
    "mekke": ("JED", "MED"),
    "mecca": ("JED", "MED"),
    "riyad": ("RUH",),
    "riyadh": ("RUH",),
    # AFC Asian Cup 2027 is played across three Saudi cities; DMM is the field
    # that serves Al Khobar.
    "riyad cidde ve el hobar": ("RUH", "JED", "DMM"),
    # Bahrain GP / Bahrain International Airshow -- Sakhir is a circuit, BAH is
    # the only civil airport in the country.
    "sakhir": ("BAH",),
    "sanliurfa": ("GNY",),
    # --- Africa ---------------------------------------------------------
    "nairobi": ("NBO",),
    # --- Asia / Pacific -------------------------------------------------
    # Asian Games 2026 is hosted jointly by Aichi prefecture and Nagoya.
    "aichi nagoya": ("NGO",),
    "nagoya": ("NGO",),
    # Avalon Airshow: AVV is the show's own airfield, MEL is where the
    # visitors land.
    "avalon melbourne": ("AVV", "MEL"),
    "avalon": ("AVV", "MEL"),
    "melbourne": ("AVV", "MEL"),
    "changchun": ("CGQ",),
    # FISU Summer Games 2027 are spread across Chungcheong province; Cheongju
    # is the province's own international airport.
    "chungcheong": ("CJJ",),
    "guangzhou": ("CAN",),
    "pekin": ("PEK", "PKX"),
    "beijing": ("PEK", "PKX"),
    "seul": ("ICN", "GMP"),
    "seoul": ("ICN", "GMP"),
    "singapur": ("SIN",),
    "singapore": ("SIN",),
    "xiamen": ("XMN",),
    "yeni delhi": ("DEL",),
    "new delhi": ("DEL",),
    # Yokohama is inside the Tokyo metropolitan area and is served by its
    # airports, not one of its own.
    "yokohama": ("HND", "NRT"),
    "tokyo": ("HND", "NRT"),
    "zhuhai": ("ZUH",),
    # --- Americas -------------------------------------------------------
    "calgary": ("YYC",),
    "las vegas": ("LAS",),
    "lima": ("LIM",),
    "orlando": ("MCO", "SFB"),
    "rio de janeiro": ("GIG", "SDU"),
    "santiago": ("SCL",),
    "sikago": ("ORD", "MDW"),
    "chicago": ("ORD", "MDW"),
    "new york": ("JFK", "EWR", "LGA"),
    # --- Not cities -----------------------------------------------------
    #
    # The calendar carries country-wide and global entries -- a national
    # holiday, a World Cup played in eight cities, a religious observance. They
    # are listed here rather than left out so that a *new* city added to the
    # seed fails the coverage test instead of silently resolving to nothing;
    # an empty tuple is a curated answer, a missing key is an oversight.
    "abd geneli": (),
    "avrupa geneli": (),
    "avustralya geneli": (),
    "avustralya yeni zelanda ve png geneli": (),
    "brezilya 8 sehir": (),
    "cin geneli": (),
    "hindistan geneli": (),
    "islam dunyasi geneli": (),
    "japonya geneli": (),
    "kenya tanzanya ve uganda geneli": (),
    "kuresel": (),
    "polonya geneli": (),
    "tayland geneli": (),
    "turkiye ve islam dunyasi": (),
}


@cache
def airports_for_city(city: str | None) -> tuple[str, ...]:
    """IATA codes for an events-calendar city, or `()` when there are none.

    `()` covers two different situations on purpose, because the caller can do
    nothing different about them: the entry is not a city (a country-wide
    holiday), or it is a city nobody has curated yet. Neither is worth guessing
    at -- see the module docstring for what guessing produced.
    """
    if not city:
        return ()
    return CITY_AIRPORTS.get(fold_city(city), ())
