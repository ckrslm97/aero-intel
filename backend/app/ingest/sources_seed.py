"""Curated list of free, working aviation RSS feeds -- verified reachable and
serving real RSS/Atom XML (not a login wall or an empty feed) as of this build.
Upserted into the `sources` table on startup/ingestion so the app has real
sources without any manual setup.
"""
from dataclasses import dataclass


@dataclass
class SourceSeed:
    name: str
    url: str
    source_type: str  # rss | premium
    category: str  # org | airline | airport | financial | other
    trust_weight: float
    is_premium_stub: bool = False


FREE_RSS_SOURCES: list[SourceSeed] = [
    SourceSeed("Simple Flying", "https://simpleflying.com/feed/", "rss", "other", 0.6),
    SourceSeed("AirlineGeeks", "https://airlinegeeks.com/feed/", "rss", "other", 0.6),
    SourceSeed("Aviation Week", "https://aviationweek.com/rss.xml", "rss", "other", 0.85),
    SourceSeed("ACI", "https://aci.aero/feed/", "rss", "org", 0.9),
    SourceSeed("Eurocontrol", "https://www.eurocontrol.int/rss.xml", "rss", "org", 0.9),
    SourceSeed("Airport Technology", "https://www.airport-technology.com/feed/", "rss", "airport", 0.7),
    SourceSeed("FAA", "https://www.faa.gov/rss.xml", "rss", "org", 0.95),
    SourceSeed("ICAO", "https://www.icao.int/rss.xml", "rss", "org", 0.95),
    SourceSeed("Flightradar24 Blog", "https://www.flightradar24.com/blog/feed/", "rss", "other", 0.65),
    # Skift's main feed is free; their airline-specific vertical (Skift Airline
    # Weekly) is a separate paid newsletter -- see PREMIUM_SOURCE_NAMES below.
    SourceSeed("Skift", "https://skift.com/feed/", "rss", "other", 0.7),
    # Added to widen coverage: the original ten produced only a handful of
    # articles a day, which left whole categories (events, regulatory) empty.
    # Each was checked live -- reachable, serving real RSS, and returning items;
    # candidates that 403'd or 404'd (Airways, Runway Girl, ch-aviation,
    # AINonline, AirlineRatings) were dropped rather than shipped broken.
    SourceSeed("AeroTime", "https://www.aerotime.aero/feed", "rss", "other", 0.7),
    SourceSeed("Aviation24.be", "https://www.aviation24.be/feed/", "rss", "other", 0.65),
    SourceSeed("World Airline News", "https://worldairlinenews.com/feed/", "rss", "airline", 0.65),
    SourceSeed("PaxEx.Aero", "https://paxex.aero/feed/", "rss", "other", 0.6),
    SourceSeed("AviationSource News", "https://aviationsourcenews.com/feed/", "rss", "other", 0.6),
    SourceSeed("Travel Radar", "https://www.travelradar.aero/feed/", "rss", "other", 0.55),
    SourceSeed("Aviacionline", "https://www.aviacionline.com/rss", "rss", "other", 0.6),
    SourceSeed("Aviation Today", "https://www.aviationtoday.com/feed/", "rss", "other", 0.7),
    # Round-5 additions, live-verified (200 + real items) at build time. The
    # user's priority sources are IATA and OAG: IATA publishes no public RSS
    # (pressroom is HTML-only; their data products are licensed -- covered by
    # the premium stubs below and the seeded IATA statistics), so OAG's blog is
    # the one of the two that can actually be polled. AeroRoutes is the
    # densest free source of route/network announcements (Ağ & Rota focus).
    # PhocusWire, anna.aero, Routesonline and the airline-group newsrooms were
    # all tried and dropped: 403/404/timeout or no feed at all.
    SourceSeed("OAG Blog", "https://www.oag.com/blog/rss.xml", "rss", "org", 0.85),
    SourceSeed("AeroRoutes", "https://www.aeroroutes.com/?format=rss", "rss", "other", 0.75),
    # Google News topic radars: keyless aggregator RSS scoped to the newspaper's
    # focus areas (RM / pricing / NDC / ancillary / demand) and the user's main
    # rivals. Trust sits low because items come from arbitrary publishers; our
    # own dedupe + confidence scoring does the vetting.
    SourceSeed(
        "Google News · Revenue Management",
        "https://news.google.com/rss/search?q=airline%20%22revenue%20management%22%20OR%20%22yield%20management%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Fiyatlandırma",
        "https://news.google.com/rss/search?q=airline%20pricing%20OR%20airfares&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · NDC & Dağıtım",
        "https://news.google.com/rss/search?q=airline%20NDC%20OR%20%22airline%20distribution%22%20OR%20GDS&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Ek Gelir",
        "https://news.google.com/rss/search?q=airline%20%22ancillary%20revenue%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Talep & Kapasite",
        "https://news.google.com/rss/search?q=airline%20%22load%20factor%22%20OR%20%22capacity%20growth%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Ana Rakipler",
        "https://news.google.com/rss/search?q=%22Emirates%22%20OR%20%22Qatar%20Airways%22%20OR%20%22Etihad%22%20OR%20%22Lufthansa%22%20OR%20%22Air%20France%22%20OR%20%22KLM%22%20OR%20%22British%20Airways%22%20OR%20%22Pegasus%20Airlines%22%20OR%20%22AJet%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5,
    ),
]

# Named systems from the spec that are either licensed data products (IATA,
# OAG, Cirium, ICAO Data+, Skift Airline Weekly, CAPA, FlightGlobal -- paywalled
# or subscription-gated, no public API) or commercial GDS/revenue-management
# platforms an airline RM department would integrate with directly under a
# commercial contract (Sabre, Amadeus, PROS, Accelya, ATPCO, Lufthansa Systems)
# -- none of these expose a public API to scrape or poll. Seeded as stubs so
# they're visible in the source list and admin panel; wire in a real adapter
# per app/ingest/premium/base.py once credentials exist.
PREMIUM_SOURCE_NAMES: list[SourceSeed] = [
    SourceSeed("IATA", "https://www.iata.org", "premium", "org", 0.95, is_premium_stub=True),
    SourceSeed("OAG", "https://www.oag.com", "premium", "financial", 0.9, is_premium_stub=True),
    SourceSeed("Cirium", "https://www.cirium.com", "premium", "financial", 0.9, is_premium_stub=True),
    SourceSeed("LinkedIn", "https://www.linkedin.com", "premium", "other", 0.5, is_premium_stub=True),
    SourceSeed("CAPA", "https://centreforaviation.com", "premium", "other", 0.85, is_premium_stub=True),
    SourceSeed("FlightGlobal", "https://www.flightglobal.com", "premium", "other", 0.85, is_premium_stub=True),
    SourceSeed(
        "Skift Airline Weekly", "https://airlineweekly.skift.com", "premium", "financial", 0.85,
        is_premium_stub=True,
    ),
    SourceSeed("ICAO Data+", "https://www.icao.int/data", "premium", "org", 0.9, is_premium_stub=True),
    SourceSeed("ATPCO", "https://www.atpco.net", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed("Sabre", "https://www.sabre.com", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed("Amadeus", "https://amadeus.com", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed("PROS", "https://pros.com", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed("Accelya", "https://www.accelya.com", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed(
        "Lufthansa Systems", "https://www.lufthansa-systems.com", "premium", "financial", 0.8,
        is_premium_stub=True,
    ),
]

ALL_SOURCES: list[SourceSeed] = FREE_RSS_SOURCES + PREMIUM_SOURCE_NAMES
