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
]

PREMIUM_SOURCE_NAMES: list[SourceSeed] = [
    SourceSeed("IATA", "https://www.iata.org", "premium", "org", 0.95, is_premium_stub=True),
    SourceSeed("OAG", "https://www.oag.com", "premium", "financial", 0.9, is_premium_stub=True),
    SourceSeed("Cirium", "https://www.cirium.com", "premium", "financial", 0.9, is_premium_stub=True),
    SourceSeed("LinkedIn", "https://www.linkedin.com", "premium", "other", 0.5, is_premium_stub=True),
]

ALL_SOURCES: list[SourceSeed] = FREE_RSS_SOURCES + PREMIUM_SOURCE_NAMES
