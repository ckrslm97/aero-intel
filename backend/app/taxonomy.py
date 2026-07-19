"""Canonical article taxonomy shared by the heuristic categorizer, the live LLM
prompts, the enrichment pipeline, and the /articles API. The frontend
(frontend/src/lib/taxonomy.ts) mirrors these exact slugs with Turkish labels and
colors for display -- keep both files in sync when the taxonomy changes.
"""
from dataclasses import dataclass, field


@dataclass
class SubcategoryDef:
    slug: str
    keywords: list[str]


@dataclass
class CategoryDef:
    slug: str
    keywords: list[str]
    subcategories: list[SubcategoryDef] = field(default_factory=list)


# Order matters: this is also the default display/ranking order (Revenue
# Management first, per the RM-department focus of this portal).
CATEGORIES: list[CategoryDef] = [
    CategoryDef(
        slug="revenue_management",
        keywords=[
            "yield", "rask", "cask", "load factor", "fare", "fares", "pricing", "ancillary",
            "competitor", "capacity", "demand", "overbooking", "dynamic pricing",
            "ndc", "distribution", "revenue management", "unit revenue", "fare war",
            "price war", "airfare", "ticket price", "premium cabin", "business class",
            "booking", "bookings", "yield management", "capacity discipline", "seat sale",
            "revenue per", "load factors", "pricing power", "demand outlook", "rpk", "ask",
            "upsell", "bundling", "fare class", "revenue growth", "unbundling",
        ],
        subcategories=[
            SubcategoryDef(
                "competitor",
                [
                    "competitor", "rival", "undercut", "market share", "competition",
                    "compete", "vs ", "battle",
                    # The user's named main rivals: an RM-category story about any
                    # of these airlines IS competitor intelligence, whether or not
                    # it uses the word "competitor".
                    "emirates", "qatar airways", "etihad", "lufthansa", "air france",
                    "klm", "british airways", "pegasus", "ajet",
                ],
            ),
            # NOTE: the old "region" subcategory is gone -- keyword matching
            # almost never assigned it (0 articles in production), and the
            # newspaper now has a real region filter driven by the entity-derived
            # enrichment.region field, which covers every category at once.
            SubcategoryDef(
                "pricing",
                [
                    "fare", "pricing", "price hike", "price cut", "dynamic pricing", "airfare",
                    "ticket price", "cheaper", "expensive", "fare war", "seat sale", "discount",
                ],
            ),
            SubcategoryDef(
                "promotion",
                # Compound phrases only: bare "sale"/"offer" match aircraft
                # sales and codeshare offers, which are not promotions.
                [
                    "promotion", "promo code", "promotional fare", "flash sale", "fare sale",
                    "seat sale", "special offer", "discount code", "black friday",
                    "kampanya", "indirim",
                ],
            ),
            SubcategoryDef(
                "demand_capacity",
                ["demand", "capacity", "overbooking", "forecast", "bookings", "traffic growth", "seats"],
            ),
            SubcategoryDef("load_factor", ["load factor", "seat factor", "occupancy", "load factors"]),
            SubcategoryDef(
                "ancillary",
                ["ancillary", "baggage fee", "seat selection", "upsell", "bundling", "extra fee", "add-on"],
            ),
            SubcategoryDef(
                "distribution",
                ["ndc", "distribution", "gds", "direct booking", "ota", "travel agent", "booking channel"],
            ),
        ],
    ),
    CategoryDef(
        slug="fleet",
        # Deliberately excludes bare "aircraft", "engine", "cabin" and "jet":
        # they're near-stopwords in aviation copy and made fleet swallow ~40% of
        # everything. Model designations and fleet-specific phrases carry the
        # signal instead. ("grounding" lives in safety, where it belongs.)
        keywords=[
            "aircraft order", "aircraft delivery", "delivery", "deliveries", "boeing", "airbus",
            "fleet", "widebody", "narrowbody", "embraer", "bombardier", "a320", "a321", "a350",
            "a330", "a380", "737", "787", "777", "767", "dreamliner", "737 max",
            "retrofit", "lessor", "leasing", "jet order", "fleet plan", "e175", "e190",
            "aircraft purchase", "firm order", "fleet renewal", "retirement",
        ],
        subcategories=[
            SubcategoryDef(
                "order_delivery",
                ["order", "delivery", "purchase agreement", "firm order", "deliveries", "lease", "commitment"],
            ),
            SubcategoryDef(
                "maintenance",
                ["maintenance", "mro", "overhaul", "inspection", "retrofit", "engine issue", "repair", "check"],
            ),
        ],
    ),
    CategoryDef(
        slug="network",
        keywords=[
            "route", "nonstop", "launch flight", "service between", "network", "frequency",
            "new route", "direct flight", "connects", "schedule", "seasonal service",
            "routes", "flights between", "resume", "resumes", "hub", "codeshare",
            "destination", "expands to", "launches service", "adds flights", "drops route",
        ],
        subcategories=[
            SubcategoryDef(
                "new_route",
                ["launch", "new route", "new service", "nonstop", "adds flights", "expands to", "resumes", "debut"],
            ),
            SubcategoryDef(
                "cancellation",
                ["cancel", "suspend", "discontinue", "axed", "drops route", "cuts", "ends service", "exit"],
            ),
            SubcategoryDef(
                "seasonal",
                ["seasonal", "summer schedule", "winter schedule", "summer season", "peak season"],
            ),
        ],
    ),
    CategoryDef(
        slug="finance",
        keywords=[
            "revenue", "profit", "earnings", "stock", "shares", "ipo", "quarterly", "loss", "margin",
            "results", "financial", "guidance", "outlook", "investor", "dividend", "debt",
            "bankruptcy", "chapter 11", "merger", "acquisition", "stake", "valuation",
            "net income", "ebit", "q1", "q2", "q3", "q4", "full-year", "billion", "profitability",
        ],
        subcategories=[
            SubcategoryDef(
                "results",
                ["earnings", "quarterly", "profit", "loss", "results", "net income", "ebit", "full-year"],
            ),
            SubcategoryDef(
                "equity", ["stock", "shares", "ipo", "market cap", "investor", "dividend", "stake", "shareholder"]
            ),
        ],
    ),
    CategoryDef(
        slug="safety",
        keywords=[
            "crash", "incident", "emergency", "mayday", "diverted", "grounded", "investigation",
            "accident", "ntsb", "aaib", "turbulence", "near miss", "runway excursion",
            "evacuation", "smoke", "fire", "injured", "fatal", "safety", "malfunction",
            "emergency landing", "bird strike", "depressurisation", "depressurization",
        ],
    ),
    CategoryDef(
        slug="regulatory",
        keywords=[
            "faa", "easa", "icao", "regulation", "certification", "government", "ban",
            "regulator", "approval", "certified", "rule", "law", "policy", "sanction",
            "tariff", "airspace", "bilateral", "slot rules", "compensation rules", "eu261",
            "dot", "caa", "shgm", "authority", "directive", "airworthiness", "mandate",
        ],
    ),
    CategoryDef(
        slug="sustainability",
        keywords=[
            "saf", "sustainable aviation fuel", "emissions", "carbon", "net zero",
            "sustainability", "green", "climate", "corsia", "offset", "hydrogen",
            "electric aircraft", "biofuel", "decarbon", "environmental", "noise",
        ],
    ),
    CategoryDef(
        slug="airport",
        keywords=[
            "airport", "terminal", "runway", "expansion", "slot",
            "hub airport", "gate", "concourse", "apron", "baggage handling",
            "airport capacity", "new terminal", "airport opens", "ground handling",
            "security checkpoint", "customs", "passenger experience", "lounge",
        ],
    ),
    CategoryDef(
        slug="labor",
        keywords=[
            "union", "strike", "pilots", "contract negotiation", "staffing",
            "cabin crew", "flight attendant", "walkout", "industrial action", "pay deal",
            "labour", "labor", "workforce", "hiring", "layoff", "job cuts", "recruitment",
            "collective agreement", "shortage", "wage",
        ],
    ),
    CategoryDef(
        slug="events",
        keywords=[
            "conference", "summit", "air show", "airshow", "expo", "forum", "exhibition",
            "agm", "iata agm", "farnborough", "paris air show", "dubai airshow",
            "routes world", "world aviation festival", "aix", "apex", "mro europe",
            "trade show", "convention", "symposium", "congress", "aviation week event",
            "keynote", "delegates", "exhibitors", "singapore airshow",
        ],
        subcategories=[
            # "general" / "regional" aren't keyword-detected -- an events article
            # is "regional" whenever a region is detected via detect_region(),
            # otherwise it's "general". See app/llm/heuristic.py subcategorize().
            SubcategoryDef("general", []),
            SubcategoryDef("regional", []),
        ],
    ),
]

# The user's named main rivals (IATA codes) -- powers the newspaper's
# "Ana Rakipler" filter (airline=RIVALS matches any of these). TK is the home
# carrier and deliberately not in this list.
RIVAL_CODES: tuple[str, ...] = ("AF", "BA", "EK", "EY", "KL", "LH", "PC", "QR", "VF")

# "general" is the fallback category: whatever scores zero against every
# category above lands here. It has no keyword list or subcategories of its own.
GENERAL_CATEGORY = "general"
CATEGORY_SLUGS: list[str] = [c.slug for c in CATEGORIES] + [GENERAL_CATEGORY]

CATEGORY_KEYWORDS: dict[str, list[str]] = {c.slug: c.keywords for c in CATEGORIES}
SUBCATEGORY_KEYWORDS: dict[str, dict[str, list[str]]] = {
    c.slug: {s.slug: s.keywords for s in c.subcategories} for c in CATEGORIES if c.subcategories
}

# Country (as extracted by the entity gazetteer, see app/llm/gazetteer.py) ->
# world region slug. Mirrors frontend/src/lib/taxonomy.ts `worldRegions`. This
# is a practical approximation, not an authoritative geopolitical grouping --
# e.g. Turkey is grouped with Middle East here to match how airline
# revenue-management teams typically benchmark it against Gulf carriers.
COUNTRY_TO_REGION: dict[str, str] = {
    "united kingdom": "europe", "france": "europe", "germany": "europe",
    "spain": "europe", "italy": "europe", "netherlands": "europe",
    "russia": "europe", "greece": "europe", "portugal": "europe",
    "switzerland": "europe", "austria": "europe", "belgium": "europe",
    "poland": "europe", "sweden": "europe", "norway": "europe",
    "denmark": "europe", "finland": "europe", "ireland": "europe",
    "iceland": "europe",
    "turkey": "middle-east", "qatar": "middle-east", "united arab emirates": "middle-east",
    "saudi arabia": "middle-east", "israel": "middle-east",
    "egypt": "africa", "south africa": "africa", "nigeria": "africa",
    "kenya": "africa", "morocco": "africa",
    "united states": "north-america", "canada": "north-america",
    "mexico": "central-america", "panama": "central-america", "costa rica": "central-america",
    "brazil": "south-america", "argentina": "south-america", "chile": "south-america",
    "colombia": "south-america", "peru": "south-america", "ecuador": "south-america",
    "china": "asia", "japan": "asia", "south korea": "asia", "india": "asia",
    "indonesia": "southeast-asia", "thailand": "southeast-asia", "vietnam": "southeast-asia",
    "philippines": "southeast-asia", "singapore": "southeast-asia",
    "australia": "oceania", "new zealand": "oceania",
}
