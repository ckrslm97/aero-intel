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
    "all nippon airways": ("All Nippon Airways", "NH"),
    "ana": ("All Nippon Airways", "NH"),
    "japan airlines": ("Japan Airlines", "JL"),
    "korean air": ("Korean Air", "KE"),
    "saudia": ("Saudia", "SV"),
    "flydubai": ("flydubai", "FZ"),
    "aeroflot": ("Aeroflot", "SU"),
    "iberia": ("Iberia", "IB"),
    "virgin atlantic": ("Virgin Atlantic", "VS"),
}

# name/alias (lowercase) -> (canonical name, IATA code)
AIRPORTS: dict[str, tuple[str, str]] = {
    "heathrow": ("London Heathrow", "LHR"),
    "gatwick": ("London Gatwick", "LGW"),
    "istanbul airport": ("Istanbul Airport", "IST"),
    "jfk": ("John F. Kennedy International", "JFK"),
    "los angeles international": ("Los Angeles International", "LAX"),
    "lax": ("Los Angeles International", "LAX"),
    "dubai international": ("Dubai International", "DXB"),
    "hamad international": ("Hamad International", "DOH"),
    "changi": ("Singapore Changi", "SIN"),
    "charles de gaulle": ("Paris Charles de Gaulle", "CDG"),
    "schiphol": ("Amsterdam Schiphol", "AMS"),
    "frankfurt airport": ("Frankfurt Airport", "FRA"),
    "hartsfield-jackson": ("Hartsfield-Jackson Atlanta", "ATL"),
    "o'hare": ("Chicago O'Hare", "ORD"),
    "haneda": ("Tokyo Haneda", "HND"),
    "narita": ("Tokyo Narita", "NRT"),
    "hong kong international": ("Hong Kong International", "HKG"),
    "sydney airport": ("Sydney Kingsford Smith", "SYD"),
    "abu dhabi international": ("Abu Dhabi International", "AUH"),
    "sabiha gokcen": ("Istanbul Sabiha Gokcen", "SAW"),
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
