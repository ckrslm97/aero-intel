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
    # NOTE (round 7): icao.int started answering 403 to our egress IP on every
    # retry. Left in place because it may just be a regional/WAF block that CI
    # doesn't hit -- check the ingestion error log before deleting it. EASA
    # below now carries the regulatory beat.
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
    # ---------------------------------------------------------------------
    # Round-7 expansion. Every URL below was fetched live at build time with a
    # browser User-Agent and kept only if it returned HTTP 200 *and* at least
    # three <item>/<entry> elements. Everything that failed is written up in
    # the DROPPED_CANDIDATES block after this list -- do not re-add a dropped
    # feed without re-verifying it first.
    # ---------------------------------------------------------------------
    # Regulators / institutions.
    # FAA and ICAO were removed after being verified against the *application's*
    # own User-Agent rather than a browser's: FAA 403s our crawler outright and
    # ICAO answers 200 with zero <item> elements (the feed is HTML now). Both
    # had produced exactly 0 articles since being seeded -- confirmed in
    # production -- so they were shipping the appearance of regulator coverage
    # without the substance. EASA and Eurocontrol carry that beat instead.
    SourceSeed(
        "EASA", "https://www.easa.europa.eu/en/newsroom-and-events/news/rss.xml",
        "rss", "org", 0.95,
    ),
    # International trade press.
    SourceSeed("FlightGlobal News", "https://www.flightglobal.com/rss", "rss", "other", 0.85),
    SourceSeed("The Air Current", "https://theaircurrent.com/feed/", "rss", "other", 0.8),
    SourceSeed(
        "Aviation Business News", "https://www.aviationbusinessnews.com/feed/",
        "rss", "other", 0.7,
    ),
    SourceSeed("aeroTELEGRAPH", "https://www.aerotelegraph.com/feed", "rss", "other", 0.65),
    SourceSeed(
        "Future Travel Experience", "https://www.futuretravelexperience.com/feed/",
        "rss", "other", 0.6,
    ),
    # Loyalty / passenger-experience blogs: weak on hard facts but the fastest
    # movers on fare sales, award-chart devaluations and cabin changes.
    SourceSeed("The Points Guy", "https://thepointsguy.com/feed/", "rss", "other", 0.6),
    SourceSeed("One Mile at a Time", "https://onemileatatime.com/feed/", "rss", "other", 0.6),
    SourceSeed("View from the Wing", "https://viewfromthewing.com/feed/", "rss", "other", 0.6),
    SourceSeed("Live and Let's Fly", "https://liveandletsfly.com/feed/", "rss", "other", 0.55),
    # Analysis desks -- low volume, high signal on fleet/network economics.
    SourceSeed("AirInsight", "https://airinsight.com/feed/", "rss", "other", 0.7),
    SourceSeed("TNMT", "https://www.tnmt.com/feed/", "rss", "other", 0.7),
    SourceSeed("Aviation Analysis", "https://www.aviationanalysis.net/feed/", "rss", "other", 0.55),
    # Cargo: belly capacity and freighter yields move passenger network planning.
    SourceSeed("Air Cargo News", "https://www.aircargonews.net/feed/", "rss", "other", 0.7),
    SourceSeed("Air Cargo Week", "https://aircargoweek.com/feed/", "rss", "other", 0.6),
    SourceSeed("STAT Times Air Cargo", "https://www.stattimes.com/rss/air-cargo", "rss", "other", 0.6),
    # Business aviation / general aviation.
    SourceSeed(
        "Corporate Jet Investor", "https://www.corporatejetinvestor.com/feed/",
        "rss", "other", 0.6,
    ),
    SourceSeed("AVweb", "https://www.avweb.com/feed/", "rss", "other", 0.6),
    # Fast-moving operational and enthusiast desks.
    SourceSeed("AirLive", "https://airlive.net/feed/", "rss", "other", 0.55),
    SourceSeed("Sam Chui", "https://samchui.com/feed/", "rss", "other", 0.5),
    # Travel/tourism economy.
    SourceSeed("eTurboNews", "https://www.eturbonews.com/feed/", "rss", "other", 0.55),
    # Airline newsrooms. Only a handful of carriers publish a real feed; the
    # rest are behind a CDN bot wall (see DROPPED_CANDIDATES).
    SourceSeed("Delta News Hub", "https://news.delta.com/rss.xml", "rss", "airline", 0.75),
    # Reddit: keyless .rss endpoints. Community chatter, so trust is the lowest
    # in the list -- useful as an early-warning signal, never as a sole source.
    SourceSeed("Reddit r/aviation", "https://www.reddit.com/r/aviation/.rss", "rss", "other", 0.35),
    SourceSeed(
        "Reddit r/awardtravel", "https://www.reddit.com/r/awardtravel/.rss", "rss", "other", 0.35,
    ),
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
    # Round 6, both verified live 2026-07-19 (100 items each):
    # TK radar feeds the BİZ page's news stream; the promo radar is the
    # *ongoing* source of rival campaign news (promos_seed.py is only a
    # point-in-time snapshot -- airline offer pages themselves are
    # bot-protected and can't be polled).
    SourceSeed(
        "Google News · Türk Hava Yolları",
        "https://news.google.com/rss/search?q=%22Turkish%20Airlines%22%20OR%20%22T%C3%BCrk%20Hava%20Yollar%C4%B1%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5,
    ),
    SourceSeed(
        "Google News · Rakip Kampanyalar",
        "https://news.google.com/rss/search?q=(%22Emirates%22%20OR%20%22Qatar%20Airways%22%20OR%20%22Lufthansa%22%20OR%20%22Air%20France%22%20OR%20%22British%20Airways%22%20OR%20%22Etihad%22%20OR%20%22KLM%22%20OR%20%22Pegasus%20Airlines%22%20OR%20%22AJet%22)%20(%22fare%20sale%22%20OR%20%22promotion%22%20OR%20%22discount%22%20OR%20%22flash%20sale%22)&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5,
    ),
    # Round-7 radars: seven focus areas the publisher desks under-cover. Volume
    # is bounded by AGGREGATOR_ITEM_CAP in app/ingest/rss.py (40 items/run) and
    # the relevance gate, so these widen recall without flooding the LLM stage.
    SourceSeed(
        "Google News · Bagaj & Ek Ücretler",
        "https://news.google.com/rss/search?q=airline%20%22baggage%20fee%22%20OR%20%22seat%20selection%20fee%22%20OR%20%22checked%20bag%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Sadakat Programları",
        "https://news.google.com/rss/search?q=airline%20%22loyalty%20program%22%20OR%20%22frequent%20flyer%22%20OR%20%22award%20miles%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · İttifak & Ortak Uçuş",
        "https://news.google.com/rss/search?q=airline%20codeshare%20OR%20%22joint%20venture%22%20OR%20%22Star%20Alliance%22%20OR%20oneworld%20OR%20SkyTeam&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5,
    ),
    SourceSeed(
        "Google News · Kapasite Kesintileri",
        "https://news.google.com/rss/search?q=airline%20%22capacity%20cuts%22%20OR%20%22route%20suspension%22%20OR%20%22cancels%20route%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5,
    ),
    SourceSeed(
        "Google News · Dinamik Fiyatlama",
        "https://news.google.com/rss/search?q=airline%20%22dynamic%20pricing%22%20OR%20%22continuous%20pricing%22%20OR%20%22offer%20and%20order%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5,
    ),
    SourceSeed(
        "Google News · Slot & Hub",
        "https://news.google.com/rss/search?q=%22airport%20slots%22%20OR%20%22slot%20allocation%22%20OR%20%22hub%20expansion%22%20airline&hl=en-US&gl=US&ceid=US:en",
        "rss", "airport", 0.5,
    ),
    SourceSeed(
        "Google News · İstanbul Havalimanları",
        "https://news.google.com/rss/search?q=%22Istanbul%20Airport%22%20OR%20%22Sabiha%20G%C3%B6k%C3%A7en%22%20OR%20%22DHM%C4%B0%22&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airport", 0.5,
    ),
]

# Documented drops -- candidates fetched at round-7 build time that failed the
# "HTTP 200 + at least three items" bar. Kept here so nobody spends another
# afternoon rediscovering them; re-verify before promoting any of these.
#
# Regulators / institutions
#   IATA pressroom        https://www.iata.org/en/pressroom/rss/            404 (HTML pressroom only, no feed)
#   UK CAA                https://www.caa.co.uk/rss/news/                   403 (bot wall)
#   US DOT                https://www.transportation.gov/rss/press-releases 403
#   Transport Canada      https://www.tc.gc.ca/rss/aviation.xml             404
#   NTSB press releases   .../press-releases?rss=1                          200 but 0 items (HTML page)
#   ECAC                  https://www.ecac-ceac.org/rss.xml                 200 but 0 items
#   BEA France            https://www.bea.aero/en/rss.xml                   404
#   Royal Aeronautical    https://www.aerosociety.com/rss/                  404
# Trade press
#   ch-aviation           /portal/rss/news                                  404 (feed retired, now paywalled)
#   Airways               airwaysmag.com/feed, airways.com/feed             404 / 200 with 0 items
#   Runway Girl Network   https://runwaygirlnetwork.com/feed/               403 (still, as in round 4)
#   AINonline             /rss.xml and /feeds/rss.xml                       404
#   AirlineRatings        https://www.airlineratings.com/feed/              404
#   anna.aero             https://www.anna.aero/feed/                       connection timeout
#   Routesonline          https://www.routesonline.com/rss/                 404
#   Intl Airport Review   https://www.internationalairportreview.com/feed/  404
#   AviationPros          https://www.aviationpros.com/rss                  404
#   Aviation Week AWIN    aviationweek.com/rss/awst, /awin/rss.xml          404 (main rss.xml already seeded)
#   PhocusWire            /rss and /rss/latest-news                         403
#   Travel Weekly         https://www.travelweekly.com/rss/all-news         403
#   TravelPulse           https://www.travelpulse.com/rss                   403
#   Travel And Tour World https://www.travelandtourworld.com/feed/          403
#   Breaking Travel News  https://www.breakingtravelnews.com/rss/           404
#   Tourism Review        https://www.tourism-review.com/rss/               200 but 0 items
#   FlyerTalk             https://www.flyertalk.com/feed                    403
#   Aviation Herald       https://avherald.com/rss/                         404
#   APEX                  https://apex.aero/feed                            200, only 2 items
# Airline newsrooms (nearly all sit behind a CDN bot wall or publish HTML only)
#   Lufthansa Group       newsroom.lufthansagroup.com/en/rss/all.xml        404
#   Air France-KLM        https://www.airfranceklm.com/en/rss.xml           403
#   IAG                   https://www.iairgroup.com/rss/                    404
#   American Airlines     https://news.aa.com/rss/                          403
#   United                https://www.united.com/en/us/newsroom/rss         connection reset
#   Ryanair               https://corporate.ryanair.com/feed/               404
#   easyJet               https://mediacentre.easyjet.com/feed/             404
#   Wizz Air              wizzair.com/.../news/rss                          200 but 0 items
#   Emirates              https://www.emirates.com/media-centre/rss/        404
#   Qatar Airways         https://press.qatarairways.com/rss                connection failed
#   (Turkish Airlines and Pegasus publish no feed at all -- both are covered
#    by the Google News radars above instead.)
# Airports
#   Heathrow              /company/rss and mediacentre.heathrow.com/rss     404
#   Schiphol              news.schiphol.com/rss (200, 0 items), newsroom... connection failed
#   Fraport               https://www.fraport.com/en/newsroom.rss.xml       200 but 0 items
#   Dubai Airports        https://www.dubaiairports.ae/rss                  404
#   Changi                https://www.changiairport.com/rss                 404
# Manufacturers
#   Airbus                https://www.airbus.com/en/rss.xml                 200 but 0 items
#   Boeing                https://www.boeing.com/feed/rss/news              404
#   Embraer               https://www.embraer.com/global/en/rss             403
# Reddit
#   r/airlines            https://www.reddit.com/r/airlines/.rss            403 (restricted sub)
#   r/flying, r/travel    .../.rss                                          429 on every retry; Reddit
#                                                                           rate-limits our egress IP, so
#                                                                           only two subs were kept.
# Off-topic / too broad to be worth the ingest budget: Economist Business,
# BBC Business, MercoPress, Flying Magazine, Rotor & Wing, Aerospace Testing
# International, Aerospace Manufacturing & Design -- all returned valid feeds
# but almost no airline-commercial content.

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
