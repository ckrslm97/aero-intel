"""Static lookup tables backing the no-key heuristic entity extractor. Not
exhaustive -- a practical starting set that's easy to extend; a real NER model
(spaCy/transformers) or LLM-based extraction can replace this behind the same
LLMProvider interface without touching callers.
"""

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
AIRPORT_COUNTRY: dict[str, str] = {
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
AIRPORTS: dict[str, tuple[str, str]] = {
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
}

# ISO-ish common country names, lowercase
COUNTRIES: set[str] = {
    "united states", "united kingdom", "france", "germany", "turkey", "qatar",
    "united arab emirates", "china", "japan", "south korea", "india", "australia",
    "canada", "brazil", "mexico", "spain", "italy", "netherlands", "russia",
    "saudi arabia", "singapore", "indonesia", "thailand", "vietnam", "philippines",
    "egypt", "south africa", "nigeria", "kenya", "morocco", "israel", "greece",
    "portugal", "switzerland", "austria", "belgium", "poland", "sweden", "norway",
    "denmark", "finland", "ireland", "iceland", "new zealand", "argentina",
    "chile", "colombia", "peru", "ecuador", "panama", "costa rica",
}
