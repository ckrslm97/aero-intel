"""Lookup tables backing the no-key heuristic entity extractor. A real NER
model (spaCy/transformers) or LLM-based extraction can replace this behind the
same LLMProvider interface without touching callers.

Two layers, and the order matters:

  * the **generated** layer -- ~3.2k IATA airports and 243 countries loaded
    from app/data (see scripts/build_airports.py). This is what route news
    actually names: cities and secondary airports, "Riyadh-Malaga", "Bergen".
    Before it existed the airport table knew 19 codes and most route stories
    resolved to no region at all.
  * the **curated** layer below -- the hand-written entries and, more
    importantly, the hand-written *refusals*. Every "no bare X" note in this
    file is a measurement against production articles, not a hunch. The
    generated layer is merged in underneath, so a curated entry always wins and
    a curated refusal is never re-added by a dataset rebuild.

Matching happens on folded text (`fold_for_match`), so every alias key in the
merged tables is folded too -- they are match keys, not display strings.
"""
import re
import unicodedata

from app.data import airport_aliases, airports_by_iata, country_name, country_regions_by_name

# Diacritics NFKD does not decompose. Without this "Málaga" normalises to
# "m laga" (app.pipeline.hashing.normalize_text deletes any non-ASCII byte), so
# the alias for Málaga could never match the word Málaga -- and the curated
# "sabiha gökçen" alias had been dead on arrival for the same reason.
_FOLD_MAP = str.maketrans(
    {"ı": "i", "İ": "i", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
     "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
     "ß": "ss", "þ": "th", "Þ": "TH", "ð": "d", "Ð": "D"}
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


# The same character class as _NON_ALNUM_RE, minus the assumption that the
# text has already been lowercased. Case is not noise for the bare-code rule
# further down: "JAN" is how a wire writes an IATA code and "Jan" is how it
# writes a month, and folding is where that distinction would otherwise be
# thrown away.
_NON_ALNUM_CASED_RE = re.compile(r"[^A-Za-z0-9\s]")


def fold_tokens(text: str) -> tuple[list[str], list[str]]:
    r"""Folded tokens, and the same tokens with their original casing.

    The two lists are aligned index for index by construction: they differ
    only in the final `.lower()`, and `[^A-Za-z0-9\s]` and `[^a-z0-9\s]`
    delete the same characters once case is accounted for -- so neither list
    can split or merge a token the other keeps.
    """
    text = text.translate(_FOLD_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    cased = _WHITESPACE_RE.sub(" ", _NON_ALNUM_CASED_RE.sub(" ", text)).strip().split()
    return [token.lower() for token in cased], cased


def fold_for_match(text: str) -> str:
    """Lowercase, strip diacritics, reduce to [a-z0-9 ] tokens.

    Mirrors `scripts/build_airports.py`'s `fold()` exactly -- aliases and the
    text they are matched against have to live in the same space. Defined in
    terms of `fold_tokens` so the cased and folded views cannot drift apart.
    """
    return " ".join(fold_tokens(text)[0])


# name/alias (lowercase) -> (canonical name, IATA code)
AIRLINES: dict[str, tuple[str, str]] = {
    "air france": ("Air France", "AF"),
    "british airways": ("British Airways", "BA"),
    "emirates": ("Emirates", "EK"),
    "etihad": ("Etihad Airways", "EY"),
    "etihad airways": ("Etihad Airways", "EY"),
    "klm": ("KLM", "KL"),
    "lufthansa": ("Lufthansa", "LH"),
    "qatar airways": ("Qatar Airways", "QR"),
    "pegasus": ("Pegasus Airlines", "PC"),
    "pegasus airlines": ("Pegasus Airlines", "PC"),
    "ajet": ("AJet", "VF"),
    "turkish airlines": ("Turkish Airlines", "TK"),
    # --- Turkish-language names -------------------------------------------
    #
    # Twelve Turkish feeds run through this gazetteer and, until now, the only
    # Turkish-language carrier name in the table was "turkish airlines" -- which
    # is English. So a Turkish article about the home carrier produced no TK
    # entity at all, and the airline filter, the campaign attribution and the
    # BİZ page each silently lost every Turkish source.
    #
    # Aliases are folded (fold_for_match) before lookup, so the diacritics here
    # are for readability: "Türk Hava Yolları" is matched as "turk hava yollari"
    # and a headline that spells it without diacritics matches the same entry.
    "türk hava yolları": ("Turkish Airlines", "TK"),
    "türk havayolları": ("Turkish Airlines", "TK"),
    # The abbreviation Turkish coverage actually uses. Safe as a bare token:
    # "thy" is otherwise only archaic English, which does not appear in an
    # aviation feed.
    "thy": ("Turkish Airlines", "TK"),
    "anadolujet": ("AJet", "VF"),
    "anadolu jet": ("AJet", "VF"),
    "pegasus hava yolları": ("Pegasus Airlines", "PC"),
    "pegasus havayolları": ("Pegasus Airlines", "PC"),
    "sun express": ("SunExpress", "XQ"),
    "corendon airlines": ("Corendon Airlines", "XC"),
    "delta": ("Delta Air Lines", "DL"),
    "delta air lines": ("Delta Air Lines", "DL"),
    "united airlines": ("United Airlines", "UA"),
    "american airlines": ("American Airlines", "AA"),
    "southwest airlines": ("Southwest Airlines", "WN"),
    "ryanair": ("Ryanair", "FR"),
    "easyjet": ("easyJet", "U2"),
    "qantas": ("Qantas", "QF"),
    "singapore airlines": ("Singapore Airlines", "SQ"),
    "cathay pacific": ("Cathay Pacific", "CX"),
    "air india": ("Air India", "AI"),
    "indigo": ("IndiGo", "6E"),
    "wizz air": ("Wizz Air", "W6"),
    "jetblue": ("JetBlue Airways", "B6"),
    "alaska airlines": ("Alaska Airlines", "AS"),
    "air canada": ("Air Canada", "AC"),
    "china eastern": ("China Eastern Airlines", "MU"),
    "china southern": ("China Southern Airlines", "CZ"),
    # NOTE: no bare "ana" alias -- as a substring it matched inside
    # "management" and tagged 96 articles with All Nippon in production, and
    # even word-bounded it collides with the given name Ana in Spanish-language
    # feeds. The spelled-out form below carries the coverage.
    "all nippon airways": ("All Nippon Airways", "NH"),
    "japan airlines": ("Japan Airlines", "JL"),
    "korean air": ("Korean Air", "KE"),
    "saudia": ("Saudia", "SV"),
    "flydubai": ("flydubai", "FZ"),
    "aeroflot": ("Aeroflot", "SU"),
    "iberia": ("Iberia", "IB"),
    "virgin atlantic": ("Virgin Atlantic", "VS"),
    # Round-5 widening: Turkish market + each region's major carriers, so the
    # rival filter and region detection have entities to hang on to. Aliases
    # that are ordinary words on their own (swiss, sas, tap, spirit, frontier,
    # tui, play) only appear in unambiguous multi-word forms.
    "sunexpress": ("SunExpress", "XQ"),
    "corendon": ("Corendon Airlines", "XC"),
    "aegean": ("Aegean Airlines", "A3"),
    "lot polish": ("LOT Polish Airlines", "LO"),
    "tap air portugal": ("TAP Air Portugal", "TP"),
    "tap portugal": ("TAP Air Portugal", "TP"),
    "vueling": ("Vueling", "VY"),
    "austrian airlines": ("Austrian Airlines", "OS"),
    "brussels airlines": ("Brussels Airlines", "SN"),
    "air europa": ("Air Europa", "UX"),
    "norwegian air": ("Norwegian", "DY"),
    "scandinavian airlines": ("SAS Scandinavian Airlines", "SK"),
    "finnair": ("Finnair", "AY"),
    "icelandair": ("Icelandair", "FI"),
    "eurowings": ("Eurowings", "EW"),
    "condor": ("Condor", "DE"),
    "transavia": ("Transavia", "HV"),
    "volotea": ("Volotea", "V7"),
    "gulf air": ("Gulf Air", "GF"),
    "oman air": ("Oman Air", "WY"),
    "kuwait airways": ("Kuwait Airways", "KU"),
    "egyptair": ("EgyptAir", "MS"),
    "royal jordanian": ("Royal Jordanian", "RJ"),
    "air arabia": ("Air Arabia", "G9"),
    "jazeera airways": ("Jazeera Airways", "J9"),
    "el al": ("El Al", "LY"),
    "ethiopian airlines": ("Ethiopian Airlines", "ET"),
    "kenya airways": ("Kenya Airways", "KQ"),
    "royal air maroc": ("Royal Air Maroc", "AT"),
    "airlink": ("Airlink", "4Z"),
    "avianca": ("Avianca", "AV"),
    "latam": ("LATAM Airlines", "LA"),
    "copa airlines": ("Copa Airlines", "CM"),
    "aeromexico": ("Aeroméxico", "AM"),
    "gol linhas": ("GOL Linhas Aéreas", "G3"),
    "azul": ("Azul", "AD"),
    "westjet": ("WestJet", "WS"),
    "spirit airlines": ("Spirit Airlines", "NK"),
    "frontier airlines": ("Frontier Airlines", "F9"),
    "allegiant": ("Allegiant Air", "G4"),
    "hawaiian airlines": ("Hawaiian Airlines", "HA"),
    "vietnam airlines": ("Vietnam Airlines", "VN"),
    "vietjet": ("VietJet Air", "VJ"),
    "thai airways": ("Thai Airways", "TG"),
    "malaysia airlines": ("Malaysia Airlines", "MH"),
    "garuda": ("Garuda Indonesia", "GA"),
    "cebu pacific": ("Cebu Pacific", "5J"),
    "philippine airlines": ("Philippine Airlines", "PR"),
    "eva air": ("EVA Air", "BR"),
    "china airlines": ("China Airlines", "CI"),
    "air china": ("Air China", "CA"),
    "hainan airlines": ("Hainan Airlines", "HU"),
    "scoot": ("Scoot", "TR"),
    "jetstar": ("Jetstar", "JQ"),
    "air new zealand": ("Air New Zealand", "NZ"),
    "fiji airways": ("Fiji Airways", "FJ"),
    "air india express": ("Air India Express", "IX"),
    "akasa air": ("Akasa Air", "QP"),
    "srilankan": ("SriLankan Airlines", "UL"),
}

# Airport IATA code -> country (lowercase, matching COUNTRIES / COUNTRY_TO_REGION
# keys) so region detection still works when an article names only an airport.
# The generated table covers all ~3.2k airports; these stay as the explicit
# record for the hubs this desk watches.
_CURATED_AIRPORT_COUNTRY: dict[str, str] = {
    "LHR": "united kingdom", "LGW": "united kingdom",
    "IST": "turkey", "SAW": "turkey",
    "JFK": "united states", "LAX": "united states", "ATL": "united states", "ORD": "united states",
    "DXB": "united arab emirates", "AUH": "united arab emirates",
    "DOH": "qatar",
    "SIN": "singapore",
    "CDG": "france",
    "AMS": "netherlands",
    "FRA": "germany",
    "HND": "japan", "NRT": "japan",
    "HKG": "china",
    "SYD": "australia",
}

# name/alias (lowercase) -> (canonical name, IATA code)
#
# Aliases matter more than entries. Production check after the Hub Explorer was
# built: IST had never once been recognised, because the gazetteer only knew
# "istanbul airport" while the wires write "Istanbul Airport (IST)", "IST" or
# just "Istanbul" -- on a portal built around Turkish Airlines' hub. Bare IATA
# codes are listed only where the code is not an ordinary English word.
_CURATED_AIRPORTS: dict[str, tuple[str, str]] = {
    "heathrow": ("London Heathrow", "LHR"),
    "lhr": ("London Heathrow", "LHR"),
    "gatwick": ("London Gatwick", "LGW"),
    "lgw": ("London Gatwick", "LGW"),
    "istanbul airport": ("Istanbul Airport", "IST"),
    "istanbul havalimani": ("Istanbul Airport", "IST"),
    # The city name counts as the hub here. Measured: "Istanbul Airport" appears
    # in 2 articles out of 2.879, "Istanbul" in 23 -- the wires write "Turkish
    # Airlines' Istanbul hub", not the airport's formal name, and a hub page for
    # the home carrier's own base showing two stories would be worse than the
    # conflation. Accepted cost: coverage of the city that is not about the
    # airport lands here too.
    "istanbul": ("Istanbul Airport", "IST"),
    # Not a bare "IST". Measured against 2.879 production articles: 38 matches,
    # of which 33 were German-language stories using "ist" as the verb ("das
    # ist", "Hintergrund ist"). The five real ones all wrote "Istanbul Airport
    # (IST)", which the alias above already catches, so the bare code would
    # have bought nothing and cost 33 wrong hub links.
    "jfk": ("John F. Kennedy International", "JFK"),
    "los angeles international": ("Los Angeles International", "LAX"),
    "lax": ("Los Angeles International", "LAX"),
    "dubai international": ("Dubai International", "DXB"),
    "hamad international": ("Hamad International", "DOH"),
    "changi": ("Singapore Changi", "SIN"),
    "charles de gaulle": ("Paris Charles de Gaulle", "CDG"),
    "cdg": ("Paris Charles de Gaulle", "CDG"),
    "schiphol": ("Amsterdam Schiphol", "AMS"),
    "ams": ("Amsterdam Schiphol", "AMS"),
    "frankfurt airport": ("Frankfurt Airport", "FRA"),
    "hartsfield-jackson": ("Hartsfield-Jackson Atlanta", "ATL"),
    "o'hare": ("Chicago O'Hare", "ORD"),
    "haneda": ("Tokyo Haneda", "HND"),
    "narita": ("Tokyo Narita", "NRT"),
    "hong kong international": ("Hong Kong International", "HKG"),
    "sydney airport": ("Sydney Kingsford Smith", "SYD"),
    "abu dhabi international": ("Abu Dhabi International", "AUH"),
    "zayed international": ("Abu Dhabi International", "AUH"),
    "sabiha gokcen": ("Istanbul Sabiha Gokcen", "SAW"),
    "sabiha gökçen": ("Istanbul Sabiha Gokcen", "SAW"),
    "sabiha": ("Istanbul Sabiha Gokcen", "SAW"),
    "hamad": ("Hamad International", "DOH"),
    "dxb": ("Dubai International", "DXB"),
    # No bare "SAW" or "DOH": matching is whole-word and case-insensitive, so
    # they would tag every "the airline saw record demand" and every "doh".
    #
    # Two corrections to what the dataset would otherwise resolve on its own:
    # "Doha" is the municipality of both DOH (Hamad) and DIA (the closed old
    # Doha International, still typed large_airport upstream), and OurAirports
    # files ADB's municipality as the district "Gaziemir" rather than İzmir --
    # the third Turkish airport this desk cares about.
    "doha": ("Hamad International", "DOH"),
    "izmir": ("Izmir Adnan Menderes", "ADB"),
}

# Turkish country names, folded on the way in via _country_aliases() ->
# canonical English name (the key COUNTRY_TO_REGION uses). Written with
# diacritics for readability; fold_for_match strips them, so "Türkiye" and
# "Turkiye" reach the same key.
#
# This closes the gap that put a Turkish THY network op-ed in Aruba and a
# Ukrainian airbase strike in China: twelve Turkish-language feeds run through
# this gazetteer, and until now "turkish airlines" (English) was the only
# Turkish-adjacent string in the whole file. A Turkish article naming its own
# country's neighbours resolved nothing.
#
# Deliberately excludes ordinary Turkish words that happen to also be country
# names, the same discipline _AMBIGUOUS_COUNTRY_NAMES uses for English:
#   "Mali" -- "mali" is the common Turkish adjective for financial/fiscal
#             ("mali yıl", "mali tablo"); every finance article would resolve
#             to the country Mali.
#   "Çad", "Gine" -- short, and folded to a bare token ("cad", "gine") that
#             risks matching address abbreviations and other short strings;
#             excluded out of the same caution as their English counterparts,
#             not because a real collision was found. Both stay reachable
#             through their airports.
_TURKISH_COUNTRY_NAMES: dict[str, str] = {
    "türkiye": "turkey", "almanya": "germany", "rusya": "russia",
    "ukrayna": "ukraine", "italya": "italy", "fransa": "france",
    "ingiltere": "united kingdom", "birleşik krallık": "united kingdom",
    "ispanya": "spain", "hollanda": "netherlands", "belçika": "belgium",
    "i̇sviçre": "switzerland", "avusturya": "austria", "yunanistan": "greece",
    "portekiz": "portugal", "polonya": "poland", "i̇sveç": "sweden",
    "norveç": "norway", "danimarka": "denmark", "finlandiya": "finland",
    "i̇rlanda": "ireland", "i̇zlanda": "iceland", "çekya": "czech republic",
    "çek cumhuriyeti": "czech republic", "macaristan": "hungary",
    "romanya": "romania", "bulgaristan": "bulgaria", "hırvatistan": "croatia",
    "sırbistan": "serbia", "slovenya": "slovenia", "slovakya": "slovakia",
    "estonya": "estonia", "letonya": "latvia", "litvanya": "lithuania",
    "beyaz rusya": "belarus", "moldova": "moldova", "malta": "malta",
    "kıbrıs": "cyprus", "lüksemburg": "luxembourg", "monako": "monaco",
    "amerika": "united states", "kanada": "canada", "meksika": "mexico",
    "brezilya": "brazil", "arjantin": "argentina", "şili": "chile",
    "kolombiya": "colombia", "peru": "peru", "ekvador": "ecuador",
    "venezuela": "venezuela", "uruguay": "uruguay", "paraguay": "paraguay",
    "bolivya": "bolivia", "panama": "panama", "küba": "cuba",
    "jamaika": "jamaica", "katar": "qatar", "suudi arabistan": "saudi arabia",
    "birleşik arap emirlikleri": "united arab emirates", "umman": "oman",
    "kuveyt": "kuwait", "bahreyn": "bahrain", "i̇srail": "israel",
    "filistin": "palestinian territory", "ürdün": "jordan", "lübnan": "lebanon",
    "suriye": "syria", "irak": "iraq", "i̇ran": "iran", "yemen": "yemen",
    "mısır": "egypt", "fas": "morocco", "cezayir": "algeria",
    "tunus": "tunisia", "libya": "libya", "sudan": "sudan",
    "etiyopya": "ethiopia", "kenya": "kenya", "tanzanya": "tanzania",
    "uganda": "uganda", "nijerya": "nigeria", "gana": "ghana",
    "fildişi sahili": "côte d'ivoire", "senegal": "senegal",
    "güney afrika": "south africa", "namibya": "namibia",
    "zimbabve": "zimbabwe", "zambiya": "zambia", "angola": "angola",
    "mozambik": "mozambique", "somali": "somalia", "kongo": "democratic republic of the congo",
    "çin": "china", "japonya": "japan", "güney kore": "south korea",
    "kuzey kore": "north korea", "hindistan": "india", "pakistan": "pakistan",
    "bangladeş": "bangladesh", "sri lanka": "sri lanka", "nepal": "nepal",
    "afganistan": "afghanistan", "kazakistan": "kazakhstan",
    "özbekistan": "uzbekistan", "türkmenistan": "turkmenistan",
    "kırgızistan": "kyrgyzstan", "tacikistan": "tajikistan",
    "azerbaycan": "azerbaijan", "ermenistan": "armenia", "gürcistan": "georgia",
    "moğolistan": "mongolia", "endonezya": "indonesia", "malezya": "malaysia",
    "tayland": "thailand", "vietnam": "vietnam", "filipinler": "philippines",
    "singapur": "singapore", "myanmar": "myanmar", "kamboçya": "cambodia",
    "laos": "laos", "brunei": "brunei", "tayvan": "taiwan",
    "avustralya": "australia", "yeni zelanda": "new zealand",
    "fiji": "fiji", "kosova": "kosovo", "karadağ": "montenegro",
    "kuzey makedonya": "north macedonia", "bosna hersek": "bosnia and herzegovina",
    "arnavutluk": "albania",
}


# ISO-ish common country names, lowercase.
_CURATED_COUNTRIES: set[str] = {
    "united states", "united kingdom", "france", "germany", "turkey", "qatar",
    "united arab emirates", "china", "japan", "south korea", "india", "australia",
    "canada", "brazil", "mexico", "spain", "italy", "netherlands", "russia",
    "saudi arabia", "singapore", "indonesia", "thailand", "vietnam", "philippines",
    "egypt", "south africa", "nigeria", "kenya", "morocco", "israel", "greece",
    "portugal", "switzerland", "austria", "belgium", "poland", "sweden", "norway",
    "denmark", "finland", "ireland", "iceland", "new zealand", "argentina",
    "chile", "colombia", "peru", "ecuador", "panama", "costa rica",
}


# ---------------------------------------------------------------------------
# Merged tables. Generated data underneath, curated overlay on top.
# ---------------------------------------------------------------------------
# Country names are matched too, but the generated list is NOT poured in
# wholesale: it contains "Georgia" (a US state and a given name), "Jordan"
# (Michael), "Chad", "Guinea", "Niger" and "Mali" -- whole-word matches that
# would file an Atlanta story under Asia. Those countries stay reachable
# through their airports, which is the path route news uses anyway.
_AMBIGUOUS_COUNTRY_NAMES = {
    "chad", "dominica", "georgia", "grenada", "guinea", "jordan", "mali",
    "niger", "reunion", "saint martin", "sint maarten", "curacao",
}


def _country_aliases() -> dict[str, str]:
    """Folded alias -> canonical country name (the key COUNTRY_TO_REGION uses)."""
    aliases: dict[str, str] = {}
    for name in country_regions_by_name():
        if name in _AMBIGUOUS_COUNTRY_NAMES or len(name) < 4:
            continue
        # Parenthesised qualifiers upstream ("Western Sahara (disputed
        # territory)") are not what anyone writes; drop the whole entry rather
        # than match on a mangled prefix.
        if "(" in name:
            continue
        aliases[fold_for_match(name)] = name
    for name in _CURATED_COUNTRIES:
        aliases[fold_for_match(name)] = name
    for turkish_name, canonical in _TURKISH_COUNTRY_NAMES.items():
        aliases[fold_for_match(turkish_name)] = canonical
    return aliases


def _airport_tables() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    by_iata = airports_by_iata()
    airports: dict[str, tuple[str, str]] = {}
    for alias, code in airport_aliases().items():
        entry = by_iata.get(code)
        if entry is not None:
            airports[alias] = (entry.name, code)
    for alias, value in _CURATED_AIRPORTS.items():
        airports[fold_for_match(alias)] = value

    countries: dict[str, str] = {}
    for code, entry in by_iata.items():
        name = country_name(entry.country)
        if name:
            countries[code] = name
    countries.update(_CURATED_AIRPORT_COUNTRY)
    return airports, countries


# name/alias (folded) -> (canonical name, IATA code)
AIRPORTS: dict[str, tuple[str, str]]
# Airport IATA code -> country name, lowercase
AIRPORT_COUNTRY: dict[str, str]
AIRPORTS, AIRPORT_COUNTRY = _airport_tables()

# IATA codes that are also ordinary words, so a bare match on one is far more
# likely to be prose than an airport. Derived by intersecting the 3.2k codes
# against month abbreviations and common English/Turkish short words, not
# hand-guessed: "Okinawa Jan 2027 Launch" was matching JAN (Jackson,
# Mississippi) and filing a Taiwan-Japan story under north-america.
#
# These are NOT removed from the tables -- "flights to JAN" is a real
# reference. They are only held to the stricter rule in `extract_entities`:
# the token has to be capitalised the way a wire writes a code (JAN), not the
# way it writes a month (Jan). That is exactly the distinction `fold_tokens`
# preserves the cased view for.
AMBIGUOUS_BARE_CODES: frozenset[str] = frozenset(
    {
        # month abbreviations -- the ones that are also codes
        "JAN", "MAR", "AUG", "JUL", "NOV", "DEC",
        # ordinary English words
        "ADD", "BAY", "CAN", "CAP", "DAY", "FOR", "GET", "HAD", "HAS", "INC",
        "LTD", "SEA", "SUN", "TEN", "THE", "USA", "WIN",
        # ordinary Turkish words
        "BIR", "COK", "IKI", "TUR", "VAR", "VER",
    }
)

# folded alias -> canonical country name
COUNTRY_ALIASES: dict[str, str] = _country_aliases()
# The canonical names themselves, for callers that only need the set.
COUNTRIES: set[str] = set(COUNTRY_ALIASES.values())

# Airline aliases folded into the same match space as everything else.
AIRLINE_ALIASES: dict[str, tuple[str, str]] = {
    fold_for_match(alias): value for alias, value in AIRLINES.items()
}

# --- matcher indexes ------------------------------------------------------
# Matching is a token n-gram lookup rather than one compiled regex per alias.
# It is exactly equivalent -- normalised text is single-space-separated
# [a-z0-9] tokens, so token boundaries and regex \b boundaries coincide -- and
# it is the difference between 12k regex scans per article and one pass.
#
# `ALIAS_FIRST_TOKENS` is the prune: a position whose first token starts no
# alias cannot start a match, which skips almost every word in the body before
# any n-gram is built at all.
MAX_ALIAS_TOKENS: int = max(
    len(alias.split()) for alias in (*AIRPORTS, *COUNTRY_ALIASES, *AIRLINE_ALIASES)
)
ALIAS_FIRST_TOKENS: frozenset[str] = frozenset(
    alias.split(" ", 1)[0]
    for alias in (*AIRPORTS, *COUNTRY_ALIASES, *AIRLINE_ALIASES)
)


# City (lowercase) -> (canonical city name, country lowercase matching COUNTRIES).
#
# Used only by the Risk Radarı classifier to put a city name on an event that a
# country alone would place too vaguely ("a flood in the United States" is not
# an operationally useful row). It is deliberately small and hand-checked
# rather than generated. The bundled airport dataset above knows municipalities,
# but it only knows cities that have an airport, and a risk event lands wherever
# it lands -- so this stays the classifier's city vocabulary, and city is null
# for anything outside it. See app/llm/heuristic.py detect_risk_place().
#
# Ambiguous names are omitted on purpose, the same discipline the airline and
# airport tables above use: Nice, Split, Mobile, Reading, Bath, Frankfurt (the
# airport alias already covers it), Cordoba and Santiago (two countries each)
# would each cost more false placements than the coverage is worth. Valencia
# and San Jose were removed after the production measurement placed a lightning
# strike at Valencia, VENEZUELA and a Puracé-volcano closure in Colombia both
# in Spain -- neither country is in COUNTRY_TO_REGION, so country resolution
# failed and the city alone chose the wrong one. Matching is
# whole-word and runs over diacritic-folded text, so "Istanbul" also matches
# "İstanbul".
RISK_CITY_COUNTRY: dict[str, tuple[str, str]] = {
    # Turkey
    "istanbul": ("Istanbul", "turkey"),
    "ankara": ("Ankara", "turkey"),
    "izmir": ("Izmir", "turkey"),
    "antalya": ("Antalya", "turkey"),
    "adana": ("Adana", "turkey"),
    "kahramanmaras": ("Kahramanmaras", "turkey"),
    "hatay": ("Hatay", "turkey"),
    "gaziantep": ("Gaziantep", "turkey"),
    "bodrum": ("Bodrum", "turkey"),
    "mugla": ("Mugla", "turkey"),
    "canakkale": ("Canakkale", "turkey"),
    # Europe
    "london": ("London", "united kingdom"),
    "manchester": ("Manchester", "united kingdom"),
    "edinburgh": ("Edinburgh", "united kingdom"),
    "paris": ("Paris", "france"),
    "marseille": ("Marseille", "france"),
    "lyon": ("Lyon", "france"),
    "berlin": ("Berlin", "germany"),
    "munich": ("Munich", "germany"),
    "hamburg": ("Hamburg", "germany"),
    "madrid": ("Madrid", "spain"),
    "barcelona": ("Barcelona", "spain"),
    "seville": ("Seville", "spain"),
    "rome": ("Rome", "italy"),
    "milan": ("Milan", "italy"),
    "naples": ("Naples", "italy"),
    "catania": ("Catania", "italy"),
    "amsterdam": ("Amsterdam", "netherlands"),
    "brussels": ("Brussels", "belgium"),
    "vienna": ("Vienna", "austria"),
    "zurich": ("Zurich", "switzerland"),
    "geneva": ("Geneva", "switzerland"),
    "lisbon": ("Lisbon", "portugal"),
    "porto": ("Porto", "portugal"),
    "athens": ("Athens", "greece"),
    "thessaloniki": ("Thessaloniki", "greece"),
    "rhodes": ("Rhodes", "greece"),
    "crete": ("Crete", "greece"),
    "warsaw": ("Warsaw", "poland"),
    "krakow": ("Krakow", "poland"),
    "stockholm": ("Stockholm", "sweden"),
    "oslo": ("Oslo", "norway"),
    "copenhagen": ("Copenhagen", "denmark"),
    "helsinki": ("Helsinki", "finland"),
    "dublin": ("Dublin", "ireland"),
    "reykjavik": ("Reykjavik", "iceland"),
    "moscow": ("Moscow", "russia"),
    "st petersburg": ("St Petersburg", "russia"),
    # Middle East
    "dubai": ("Dubai", "united arab emirates"),
    "abu dhabi": ("Abu Dhabi", "united arab emirates"),
    "doha": ("Doha", "qatar"),
    "riyadh": ("Riyadh", "saudi arabia"),
    "jeddah": ("Jeddah", "saudi arabia"),
    "tel aviv": ("Tel Aviv", "israel"),
    "jerusalem": ("Jerusalem", "israel"),
    # Africa
    "cairo": ("Cairo", "egypt"),
    "alexandria": ("Alexandria", "egypt"),
    "sharm el sheikh": ("Sharm El Sheikh", "egypt"),
    "hurghada": ("Hurghada", "egypt"),
    "johannesburg": ("Johannesburg", "south africa"),
    "cape town": ("Cape Town", "south africa"),
    "durban": ("Durban", "south africa"),
    "lagos": ("Lagos", "nigeria"),
    "abuja": ("Abuja", "nigeria"),
    "nairobi": ("Nairobi", "kenya"),
    "casablanca": ("Casablanca", "morocco"),
    "marrakech": ("Marrakech", "morocco"),
    # Americas
    "new york": ("New York", "united states"),
    "los angeles": ("Los Angeles", "united states"),
    "chicago": ("Chicago", "united states"),
    "miami": ("Miami", "united states"),
    "houston": ("Houston", "united states"),
    "dallas": ("Dallas", "united states"),
    "san francisco": ("San Francisco", "united states"),
    "seattle": ("Seattle", "united states"),
    "boston": ("Boston", "united states"),
    "denver": ("Denver", "united states"),
    "atlanta": ("Atlanta", "united states"),
    "new orleans": ("New Orleans", "united states"),
    # Washington is here for the SOURCE role as much as the event one: it is
    # the standard metonym for the US government in wire copy ("Washington
    # said..."), which is exactly the construction heuristic.py's location
    # roles have to be able to see in order to refuse it as an event location.
    # Without an entry here the name is invisible to the resolver and the
    # sentence resolves to whichever country the gazetteer happened to hit
    # first -- the failure the role test exists to fix.
    "washington": ("Washington", "united states"),
    "toronto": ("Toronto", "canada"),
    "vancouver": ("Vancouver", "canada"),
    "montreal": ("Montreal", "canada"),
    "calgary": ("Calgary", "canada"),
    "mexico city": ("Mexico City", "mexico"),
    "cancun": ("Cancun", "mexico"),
    "acapulco": ("Acapulco", "mexico"),
    "panama city": ("Panama City", "panama"),
    "sao paulo": ("Sao Paulo", "brazil"),
    "rio de janeiro": ("Rio de Janeiro", "brazil"),
    "brasilia": ("Brasilia", "brazil"),
    "porto alegre": ("Porto Alegre", "brazil"),
    "buenos aires": ("Buenos Aires", "argentina"),
    "bogota": ("Bogota", "colombia"),
    "medellin": ("Medellin", "colombia"),
    "lima": ("Lima", "peru"),
    "quito": ("Quito", "ecuador"),
    "guayaquil": ("Guayaquil", "ecuador"),
    # Asia-Pacific
    "beijing": ("Beijing", "china"),
    "shanghai": ("Shanghai", "china"),
    "guangzhou": ("Guangzhou", "china"),
    "shenzhen": ("Shenzhen", "china"),
    "hong kong": ("Hong Kong", "china"),
    "tokyo": ("Tokyo", "japan"),
    "osaka": ("Osaka", "japan"),
    "sendai": ("Sendai", "japan"),
    "fukuoka": ("Fukuoka", "japan"),
    "seoul": ("Seoul", "south korea"),
    "busan": ("Busan", "south korea"),
    "delhi": ("Delhi", "india"),
    "new delhi": ("New Delhi", "india"),
    "mumbai": ("Mumbai", "india"),
    "chennai": ("Chennai", "india"),
    "kolkata": ("Kolkata", "india"),
    "bengaluru": ("Bengaluru", "india"),
    "jakarta": ("Jakarta", "indonesia"),
    "bali": ("Bali", "indonesia"),
    "denpasar": ("Denpasar", "indonesia"),
    "surabaya": ("Surabaya", "indonesia"),
    "bangkok": ("Bangkok", "thailand"),
    "phuket": ("Phuket", "thailand"),
    "chiang mai": ("Chiang Mai", "thailand"),
    "hanoi": ("Hanoi", "vietnam"),
    "ho chi minh city": ("Ho Chi Minh City", "vietnam"),
    "da nang": ("Da Nang", "vietnam"),
    "manila": ("Manila", "philippines"),
    "cebu": ("Cebu", "philippines"),
    "sydney": ("Sydney", "australia"),
    "melbourne": ("Melbourne", "australia"),
    "brisbane": ("Brisbane", "australia"),
    "perth": ("Perth", "australia"),
    "adelaide": ("Adelaide", "australia"),
    "auckland": ("Auckland", "new zealand"),
    "christchurch": ("Christchurch", "new zealand"),
    "wellington": ("Wellington", "new zealand"),
}
