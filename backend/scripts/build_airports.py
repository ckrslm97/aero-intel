#!/usr/bin/env python3
"""Regenerate the bundled airport/country reference data under app/data/.

Source: OurAirports (https://ourairports.com/data/), released into the **public
domain** -- "you can use it for any purpose, with or without attribution".
Two files are read:

    https://davidmegginson.github.io/ourairports-data/airports.csv   (~86k rows)
    https://davidmegginson.github.io/ourairports-data/countries.csv  (249 rows)

Why a build script and not a hand-maintained table: the gazetteer used to know
19 IATA codes, so every route story about a secondary airport ("Riyadh-Malaga",
"Bergen") resolved to no region at all. 86k rows is the other extreme -- most
of it heliports, seaplane bases and closed strips that no wire service will
ever name. The cut kept here is airports that (a) hold a real IATA code,
(b) are typed large_airport or medium_airport, and (c) are marked
scheduled_service=yes: ~3.2k airports, i.e. the set an airline news feed can
plausibly be talking about.

Run:  python scripts/build_airports.py            (fetches from the network)
      python scripts/build_airports.py --from-dir DIR   (uses cached CSVs)

Outputs (both pretty-printed so a regeneration is reviewable in a diff):
    app/data/airports.json    airports + the alias index the gazetteer matches on
    app/data/countries.json   ISO alpha-2 -> {name, region}
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

BASE_URL = "https://davidmegginson.github.io/ourairports-data"
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "app" / "data"
FRONTEND_REGION_MAP = (
    REPO_ROOT.parents[0] / "frontend" / "src" / "lib" / "geo" / "region-countries.ts"
)

KEEP_TYPES = {"large_airport", "medium_airport"}
# large before medium, so a city with several airports is represented by its
# primary one (London -> LHR, not LCY).
TYPE_RANK = {"large_airport": 0, "medium_airport": 1}


# --------------------------------------------------------------------------
# Region assignment
# --------------------------------------------------------------------------
# Continent -> region for the cases where the two agree. The two that do not:
# OurAirports files the Middle East under "AS" and the whole Caribbean under
# "NA", while this product's taxonomy (app/taxonomy.py, mirrored in
# frontend/src/lib/nav.ts worldRegions) treats both as their own regions.
CONTINENT_REGION = {
    "EU": "europe",
    "AF": "africa",
    "SA": "south-america",
    "OC": "oceania",
    "AS": "asia",
    "NA": "north-america",
}

# Turkey sits here rather than in Europe. It is the product's existing opinion
# (app/taxonomy.py has said so since the taxonomy was written) and it is the
# one a Turkish carrier's revenue desk works with: TK is benchmarked against
# EK/QR/EY, not against Lufthansa alone. See also app/hubs.py, where IST/SAW
# now carry the same slug.
MIDDLE_EAST = {
    "AE", "BH", "IL", "IQ", "IR", "JO", "KW", "LB", "OM",
    "PS", "QA", "SA", "SY", "TR", "YE",
}
SOUTHEAST_ASIA = {"BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "TL", "VN"}
# Mexico, the Central American isthmus, and the Caribbean.
CENTRAL_AMERICA = {
    "MX", "GT", "BZ", "SV", "HN", "NI", "CR", "PA",
    "AG", "AI", "AW", "BB", "BL", "BQ", "BS", "CU", "CW", "DM", "DO", "GD",
    "GP", "HT", "JM", "KN", "KY", "LC", "MF", "MQ", "MS", "PR", "SX", "TC",
    "TT", "VC", "VG", "VI",
}
# Countries whose continent code disagrees with where the product files them.
REGION_OVERRIDES = {
    "CY": "europe",     # filed with Europe, as the frontend map already had it
    "RU": "europe",     # trans-continental; Europe is where its traffic is
    "GL": "north-america",
    "BM": "north-america",
    "PM": "north-america",
    "GF": "south-america",
}
SKIP_COUNTRIES = {"AQ", "ZZ", "BV", "HM", "GS", "TF", "UM"}  # uninhabited / unassigned

# GeoJSON display name (frontend/src/lib/geo/region-countries.ts) -> ISO alpha-2,
# for the names the two sources spell differently. Only used by the
# cross-check below; it does not feed the generated data.
GEOJSON_ALIASES = {
    "Aland": "AX", "Antigua and Barb.": "AG", "Bosnia and Herz.": "BA",
    "Cayman Is.": "KY", "Central African Rep.": "CF", "Congo": "CG",
    "Czech Rep.": "CZ", "Dem. Rep. Congo": "CD", "Dem. Rep. Korea": "KP",
    "Dominican Rep.": "DO", "Eq. Guinea": "GQ", "Faeroe Is.": "FO",
    "Falkland Is.": "FK", "Fr. Polynesia": "PF", "Korea": "KR",
    "Lao PDR": "LA", "Macedonia": "MK", "N. Mariana Is.": "MP",
    "Palestine": "PS", "S. Sudan": "SS", "Solomon Is.": "SB",
    "St. Pierre and Miquelon": "PM", "St. Vin. and Gren.": "VC",
    "Swaziland": "SZ", "Turks and Caicos Is.": "TC", "U.S. Virgin Is.": "VI",
    "W. Sahara": "EH",
    # Deliberately unmapped: "N. Cyprus", "Siachen Glacier",
    # "S. Geo. and S. Sandw. Is." have no OurAirports country of their own.
}


def region_for(iso: str, continent: str) -> str | None:
    if iso in SKIP_COUNTRIES:
        return None
    if iso in REGION_OVERRIDES:
        return REGION_OVERRIDES[iso]
    if iso in MIDDLE_EAST:
        return "middle-east"
    if iso in SOUTHEAST_ASIA:
        return "southeast-asia"
    if iso in CENTRAL_AMERICA:
        return "central-america"
    return CONTINENT_REGION.get(continent)


# --------------------------------------------------------------------------
# Alias guards
# --------------------------------------------------------------------------
# The whole reason this file is long. A gazetteer keyed on city names and bare
# IATA codes is a false-positive machine: "Nice", "Male", "Split", "Reading"
# and "Mobile" are cities, and three-letter codes spell "IST", "SAW", "MAN",
# "SIN", "DEN" and "SAN". The existing hand-written entries in
# app/llm/gazetteer.py carry the measurements -- a bare "IST" alias matched 38
# production articles, 33 of them German sentences using "ist" as a verb.
#
# So every generated alias passes three gates: it is not a common word in any
# language the feeds are written in, it is not aviation shorthand, and it is
# not ambiguous across countries (a wrong region is worse than no region).
#
# This list is short and hand-picked on purpose. A general English dictionary
# was tried first and is the wrong tool: /usr/share/dict/words contains
# "atlanta", "berlin", "bangkok", "bordeaux", "auh", "arn", "bom" and "bud",
# so it throws away Abu Dhabi, Stockholm, Mumbai and Budapest to catch "the".
COMMON_WORDS = {
    # English function words and everyday nouns/verbs of 2-7 letters
    "a", "about", "above", "act", "add", "after", "again", "age", "aid", "aim",
    "air", "all", "also", "and", "any", "app", "are", "arm", "art", "ask",
    "at", "bad", "bag", "ban", "bar", "base", "bat", "bay", "be", "bed", "beg",
    "belt", "best", "bet", "big", "bill", "bit", "block", "blue", "boa",
    "board", "bob", "book", "boo", "boom", "boot", "box", "boy", "bus", "but",
    "buy", "by", "cab", "call", "can", "cap", "car", "card", "care", "case",
    "cash", "cat", "cent", "chief", "city", "class", "coal", "cod", "coin",
    "cold", "cop", "core", "cost", "cow", "crew", "cue", "cup", "cut", "dad",
    "dam", "dare", "dark", "data", "date", "day", "deal", "dear", "deep",
    "den", "did", "die", "dig", "dip", "dog", "dot", "down", "draw", "drop",
    "dry", "due", "each", "ear", "east", "eat", "edge", "egg", "eight", "end",
    "eve", "even", "ever", "eye", "face", "fact", "fair", "fall", "fan", "far",
    "fast", "fat", "fee", "few", "field", "fill", "find", "fine", "fire",
    "firm", "first", "fit", "five", "fix", "flag", "flat", "flow", "fly",
    "fog", "food", "foot", "for", "form", "four", "free", "from", "front",
    "fuel", "full", "fun", "gain", "game", "gap", "gas", "gate", "gay", "gem",
    "get", "gift", "gig", "give", "glass", "go", "goal", "gold", "good",
    "got", "grand", "gray", "great", "green", "grey", "grow", "gum", "gun",
    "guy", "gym", "had", "half", "hall", "ham", "hand", "hang", "hard", "has",
    "hat", "have", "he", "head", "hear", "heat", "held", "help", "her", "hid",
    "high", "hill", "him", "his", "hit", "hold", "hole", "home", "hope",
    "hot", "hour", "how", "huge", "ice", "if", "ill", "imp", "in", "ink",
    "inn", "into", "iron", "is", "it", "its", "jet", "job", "jog", "join",
    "joy", "jump", "just", "keep", "key", "kid", "kin", "king", "know", "lab",
    "lad", "lake", "land", "lane", "lap", "large", "last", "late", "law",
    "lay", "lea", "lead", "led", "leg", "less", "let", "life", "lift",
    "light", "like", "line", "link", "list", "lit", "live", "load", "loan",
    "log", "long", "look", "loo", "loss", "lost", "lot", "loud", "love",
    "low", "mad", "made", "mail", "main", "make", "male", "man", "many",
    "map", "mar", "mark", "mass", "may", "meal", "mean", "meat", "meet",
    "men", "mid", "mile", "milk", "mind", "mine", "miss", "mob", "mobile",
    "mode", "mom", "more", "most", "move", "much", "mud", "must", "name",
    "nap", "near", "neat", "need", "net", "new", "news", "next", "nice",
    "night", "nine", "no", "nor", "north", "nose", "not", "note", "now",
    "nut", "oak", "odd", "ode", "of", "off", "oil", "old", "on", "once",
    "one", "only", "open", "or", "orb", "order", "other", "our", "out",
    "over", "own", "pace", "pack", "pad", "page", "paid", "pair", "pan",
    "park", "part", "pass", "past", "pat", "pay", "peak", "pee", "peg", "pen",
    "per", "pet", "pew", "pick", "pie", "pin", "pit", "place", "plan",
    "play", "plus", "point", "pool", "poor", "pop", "port", "post", "pot",
    "power", "press", "price", "pro", "pub", "pug", "pull", "push", "put",
    "race", "rail", "rain", "raise", "ram", "ran", "range", "rank", "rap",
    "rare", "rat", "rate", "raw", "reach", "read", "reading", "real", "red",
    "rest", "rib", "rich", "ride", "ring", "rise", "risk", "road", "rob",
    "rock", "role", "roll", "room", "root", "rose", "rot", "row", "rub",
    "rule", "run", "sad", "safe", "sag", "said", "sale", "salt", "same",
    "sat", "save", "saw", "say", "sea", "seat", "see", "sell", "send",
    "sense", "sent", "set", "seven", "share", "she", "shift", "ship", "shop",
    "short", "show", "side", "sign", "sin", "since", "sir", "sit", "six",
    "size", "sky", "sly", "slot", "slow", "small", "so", "sob", "sold",
    "some", "son", "soon", "sort", "south", "sow", "space", "speed", "spend",
    "split", "spy", "staff", "stage", "stand", "star", "start", "state",
    "stay", "step", "still", "stock", "stop", "store", "story", "sub", "such",
    "sun", "sure", "swap", "tab", "table", "tag", "take", "talk", "tall",
    "tam", "tan", "tap", "task", "tax", "tea", "team", "tee", "tell", "ten",
    "term", "test", "than", "that", "the", "them", "then", "there", "these",
    "they", "thin", "this", "three", "tie", "time", "tin", "tip", "to",
    "today", "toe", "told", "ton", "too", "took", "top", "total", "tour",
    "tow", "town", "toy", "track", "trade", "train", "tree", "trip", "true",
    "try", "tub", "tug", "turn", "twin", "two", "type", "under", "unit",
    "up", "use", "used", "van", "very", "view", "visit", "vote", "wage",
    "wait", "walk", "wall", "want", "war", "warm", "was", "wave", "way",
    "we", "web", "week", "well", "went", "were", "west", "wet", "what",
    "when", "where", "which", "while", "white", "who", "why", "wide", "wild",
    "will", "win", "wind", "wing", "with", "won", "word", "work", "world",
    "would", "yak", "yard", "year", "yes", "yet", "you", "your", "zip",
    "zone",
    # Non-English function words. The feeds are multilingual and this is where
    # the worst measured false positive came from: 33 German sentences whose
    # "ist" was read as Istanbul.
    "das", "dass", "dem", "den", "der", "des", "die", "ein", "eine", "ist",
    "mit", "nicht", "sich", "und", "von", "war", "wir",
    "au", "aux", "avec", "ces", "dans", "des", "est", "les", "ne", "par",
    "pas", "plus", "pour", "que", "qui", "sur", "une", "vous",
    "con", "del", "las", "los", "mas", "para", "por", "que", "una", "uno",
    "bir", "bu", "da", "de", "ile", "ve", "icin", "daha",
    "doh",   # interjection; the old gazetteer refused a bare DOH for this
    "ana",   # "management", and a common given name -- see AIRLINES' note
    # Aviation shorthand that happens to spell an IATA code.
    "asm", "atc", "apu", "cask", "ceo", "cfo", "coo", "cto", "eta", "etd",
    "esg", "gds", "ifr", "ils", "inc", "ipo", "ltd", "mro", "mtow", "ndc",
    "neo", "pax", "plc", "rask", "rpk", "saf", "usa", "vfr", "vip",
    # Currency/ISO tokens that are also codes
    "eur", "gbp", "usd", "try",
    # Municipalities that are ordinary words or common given names. Reviewed by
    # eye against the ~2.1k single-word city aliases the cut produces; "fare"
    # (Huahine, French Polynesia) is the one that would have hurt most on a
    # revenue-management desk, where every other headline contains the word.
    "beaver", "bishop", "colon", "cork", "cruz", "david", "dole", "eagle",
    "fare", "gary", "george", "hail", "horn", "hue", "jackson", "liberal",
    "mare", "mary", "nelson", "newman", "pierre", "regina", "ruby", "saga",
    "salmon", "sidney", "terrace", "tours", "vernal", "wick",
}

# Diacritics that NFKD does not decompose, mapped by hand. Everything else is
# handled by stripping combining marks -- see fold().
_FOLD_MAP = str.maketrans(
    {"ı": "i", "İ": "i", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
     "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
     "ß": "ss", "þ": "th", "Þ": "TH", "ð": "d", "Ð": "D"}
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def fold(text: str) -> str:
    """The exact normalisation the matcher uses -- see app/llm/gazetteer.py
    `fold_for_match`. Aliases have to live in the same space as the text they
    are matched against, or "Málaga" never matches its own alias."""
    text = text.translate(_FOLD_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ALNUM_RE.sub(" ", text.lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


def read_csv(name: str, from_dir: Path | None) -> list[dict]:
    if from_dir:
        text = (from_dir / name).read_text(encoding="utf-8")
    else:
        url = f"{BASE_URL}/{name}"
        print(f"fetching {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
            text = response.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def build_countries(rows: list[dict]) -> dict[str, dict]:
    countries: dict[str, dict] = {}
    for row in rows:
        iso = row["code"]
        region = region_for(iso, row["continent"])
        if not region:
            continue
        countries[iso] = {"name": row["name"].lower(), "region": region}
    return dict(sorted(countries.items()))


def cross_check_frontend(countries: dict[str, dict]) -> int:
    """The frontend colours its world map from its own country->region map. If
    the two disagree, a signal lands in one region on the map and another in
    the ledger. Report every disagreement rather than silently picking one."""
    if not FRONTEND_REGION_MAP.exists():
        print("! frontend region map not found; skipping cross-check", file=sys.stderr)
        return 0
    text = FRONTEND_REGION_MAP.read_text(encoding="utf-8")
    frontend = dict(re.findall(r'"([^"]+)":\s*"([a-z-]+)"', text))
    by_name = {entry["name"]: iso for iso, entry in countries.items()}
    mismatches = 0
    for display_name, region in frontend.items():
        iso = GEOJSON_ALIASES.get(display_name) or by_name.get(display_name.lower())
        if not iso or iso not in countries:
            continue
        if countries[iso]["region"] != region:
            mismatches += 1
            print(
                f"! region mismatch {display_name} ({iso}): "
                f"backend={countries[iso]['region']} frontend={region}",
                file=sys.stderr,
            )
    return mismatches


def build_airports(rows: list[dict], countries: dict[str, dict]) -> list[dict]:
    kept: list[dict] = []
    for row in rows:
        iata = (row["iata_code"] or "").strip().upper()
        if len(iata) != 3 or not iata.isalpha():
            continue
        if row["type"] not in KEEP_TYPES or row["scheduled_service"] != "yes":
            continue
        if row["iso_country"] not in countries:
            continue
        try:
            lat = round(float(row["latitude_deg"]), 4)
            lon = round(float(row["longitude_deg"]), 4)
        except (TypeError, ValueError):
            continue
        kept.append(
            {
                "iata": iata,
                "name": row["name"],
                "city": row["municipality"] or "",
                "country": row["iso_country"],
                "lat": lat,
                "lon": lon,
                "_type": row["type"],
            }
        )
    kept.sort(key=lambda a: a["iata"])
    # One IATA code, one airport. The source has none today; assert rather than
    # let a future duplicate silently win.
    seen = set()
    for airport in kept:
        if airport["iata"] in seen:
            raise SystemExit(f"duplicate IATA code in source data: {airport['iata']}")
        seen.add(airport["iata"])
    return kept


def build_aliases(airports: list[dict], countries: dict[str, dict]) -> dict[str, str]:
    """alias (folded) -> IATA code.

    Four alias families, each with its own guard:
      * the bare IATA code, unless it spells a common word;
      * the airport's full name, when it is specific enough to be unmistakable;
      * "<city> airport", always safe -- the qualifier does the disambiguating;
      * the bare city name, only when it is neither a common word nor shared
        with a city in another country.
    """
    country_isos = {fold(entry["name"]): iso for iso, entry in countries.items()}

    by_city: dict[str, list[dict]] = {}
    for airport in airports:
        # "Pendik, Istanbul" / "Nice, Alpes-Maritimes": the source qualifies 39
        # municipalities with their district or department. The city proper is
        # the first segment; the qualifier is not what a wire service writes.
        city = fold(airport["city"].split(",")[0])
        if city:
            by_city.setdefault(city, []).append(airport)

    # A three-letter code that also turns up *inside* multi-word city names is
    # not a code in running text, it is a particle: DEL in "Del Rio" and "Costa
    # del Sol", SAN in "San Diego", LAS in "Las Vegas", THE in "The Valley".
    # Derived from the data rather than guessed, so it keeps working when the
    # dataset is rebuilt. Those airports keep their name and city aliases.
    token_counts: dict[str, int] = {}
    for city in by_city:
        tokens = city.split()
        if len(tokens) > 1:
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1

    # A city name that exists in two countries cannot resolve a region, so it
    # is dropped entirely: London (GB) vs London (CA), Santiago in four.
    ambiguous_cities = {
        city
        for city, group in by_city.items()
        if len({a["country"] for a in group}) > 1
    }

    # A city that spells a *different* country's name is a trap: Liberia is a
    # town in Costa Rica, Lebanon is one in Pennsylvania, Armenia one in
    # Colombia. City-states, where the two genuinely coincide, are kept.
    country_named_elsewhere = {
        city
        for city, group in by_city.items()
        if city in country_isos and all(a["country"] != country_isos[city] for a in group)
    }

    aliases: dict[str, str] = {}
    collisions: set[str] = set()

    def add(alias: str, code: str) -> None:
        if not alias or len(alias) < 3:
            return
        existing = aliases.get(alias)
        if existing is not None and existing != code:
            collisions.add(alias)
            return
        aliases[alias] = code

    for airport in airports:
        code = airport["iata"]
        lowered = code.lower()
        if lowered not in COMMON_WORDS and token_counts.get(lowered, 0) < 2:
            add(lowered, code)

        name = fold(airport["name"])
        # Two tokens minimum: a one-word airport name ("Bergen") is just the
        # city name again and goes through the city gate instead.
        if len(name.split()) >= 2 and len(name) >= 8:
            add(name, code)

    # City aliases resolve to the city's primary airport: large before medium,
    # then lowest IATA code, so the choice is deterministic across rebuilds.
    for city, group in by_city.items():
        if city in ambiguous_cities or city in country_named_elsewhere:
            continue
        primary = sorted(group, key=lambda a: (TYPE_RANK[a["_type"]], a["iata"]))[0]
        code = primary["iata"]
        # "malaga airport" is safe even when bare "nice"/"male"/"split" is not.
        add(f"{city} airport", code)
        if city not in COMMON_WORDS:
            add(city, code)

    for alias in collisions:
        aliases.pop(alias, None)
    return dict(sorted(aliases.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-dir",
        type=Path,
        help="read airports.csv/countries.csv from this directory instead of the network",
    )
    args = parser.parse_args()

    country_rows = read_csv("countries.csv", args.from_dir)
    airport_rows = read_csv("airports.csv", args.from_dir)

    countries = build_countries(country_rows)
    mismatches = cross_check_frontend(countries)
    airports = build_airports(airport_rows, countries)
    aliases = build_aliases(airports, countries)
    for airport in airports:
        airport.pop("_type")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "countries.json").write_text(
        json.dumps(countries, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (DATA_DIR / "airports.json").write_text(
        json.dumps(
            {
                "source": "OurAirports (public domain) -- https://ourairports.com/data/",
                "filter": "iata_code set, type in {large_airport, medium_airport}, scheduled_service=yes",
                "airports": airports,
                "aliases": aliases,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"{len(countries)} countries, {len(airports)} airports, "
        f"{len(aliases)} aliases, {mismatches} region mismatches"
    )


if __name__ == "__main__":
    main()
