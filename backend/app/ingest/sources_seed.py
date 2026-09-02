"""Curated list of free, working aviation RSS feeds -- verified reachable and
serving real RSS/Atom XML (not a login wall or an empty feed) as of this build.
Upserted into the `sources` table on startup/ingestion so the app has real
sources without any manual setup.
"""
from dataclasses import dataclass

#: Default `priority` per tier, so the 82 sources that predate the column get a
#: sensible value without anyone hand-typing 82 of them.
#:
#: A DEFAULT, not a definition. `tier` is the authority ladder (what kind of
#: publisher this is); `priority` is how much this desk wants the output. They
#: correlate, which is why deriving one from the other is a reasonable starting
#: point -- and they come apart at both ends, which is why a source may
#: override it. The two ends that matter here: an aggregator radar sampled at
#: ~100% fare-campaign content is worth more to the newspaper than its
#: "aggregator" tier suggests, and a national wire's general economy feed is
#: worth less than its "agency" tier suggests.
#:
#: "very_high" is deliberately absent from this table: it is reserved for
#: explicit editorial elevation, so it never arrives by derivation.
TIER_DEFAULT_PRIORITY: dict[str, str] = {
    "official": "high",
    "regulator": "high",
    "agency": "high",
    "trade": "normal",
    "aggregator": "low",
}

#: What every source is polled at today -- .github/workflows/jobs-news.yml runs
#: `0 */2 * * *`. Seeded as each source's declared cadence so the column starts
#: out telling the truth rather than describing a scheduler that doesn't exist.
DEFAULT_CRAWL_FREQUENCY_MINUTES = 120


@dataclass
class SourceSeed:
    name: str
    url: str
    source_type: str  # rss | premium
    category: str  # org | airline | airport | financial | other
    trust_weight: float
    is_premium_stub: bool = False
    #: The owner's source priority ladder: official announcement > regulator
    #: (IATA/ICAO/EASA/national authority) > agency (national wires, major
    #: press associations) > trade press > aggregator (Google News queries).
    #: Defaults to "trade" because that describes most of this list -- the
    #: independent aviation/travel press. Feeds pipeline/confidence.py directly
    #: once seeded; app/agents/runner.py no longer has to bridge from
    #: trust_weight to guess at a tier that was never declared.
    tier: str = "trade"
    #: ISO 639-1. Declared here because the feed list is curated and finite --
    #: a human already knows what language a source publishes in, which is a
    #: better answer than detecting it fresh from every article's first few
    #: hundred characters. Defaults to English, since that is what most of
    #: this list is.
    language: str = "en"
    #: very_high | high | normal | low. Left None here and filled from
    #: TIER_DEFAULT_PRIORITY in __post_init__, so a source only spells it out
    #: when the desk's judgement differs from the ladder. See the column
    #: docstring in app/models/source.py for why this is not just `tier`.
    priority: str | None = None
    #: Comma-separated app.taxonomy category slugs this source actually feeds,
    #: as measured at build time -- NOT the institution type, which is the
    #: `category` field above. None where nobody has sampled the feed for it;
    #: an empty guess would be worse than an admitted gap.
    news_categories: str | None = None
    #: Intended polling cadence. Informational -- see the column docstring.
    crawl_frequency_minutes: int = DEFAULT_CRAWL_FREQUENCY_MINUTES

    def __post_init__(self) -> None:
        if self.priority is None:
            self.priority = TIER_DEFAULT_PRIORITY.get(self.tier, "normal")


FREE_RSS_SOURCES: list[SourceSeed] = [
    SourceSeed("Simple Flying", "https://simpleflying.com/feed/", "rss", "other", 0.6),
    SourceSeed("AirlineGeeks", "https://airlinegeeks.com/feed/", "rss", "other", 0.6),
    SourceSeed("Aviation Week", "https://aviationweek.com/rss.xml", "rss", "other", 0.85),
    SourceSeed("ACI", "https://aci.aero/feed/", "rss", "org", 0.9, tier="agency"),
    SourceSeed("Eurocontrol", "https://www.eurocontrol.int/rss.xml", "rss", "org", 0.9, tier="regulator"),
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
        "rss", "org", 0.95, tier="regulator",
    ),
    # International trade press.
    SourceSeed("FlightGlobal News", "https://www.flightglobal.com/rss", "rss", "other", 0.85),
    SourceSeed("The Air Current", "https://theaircurrent.com/feed/", "rss", "other", 0.8),
    SourceSeed(
        "Aviation Business News", "https://www.aviationbusinessnews.com/feed/",
        "rss", "other", 0.7,
    ),
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
    SourceSeed("Delta News Hub", "https://news.delta.com/rss.xml", "rss", "airline", 0.75, tier="official"),
    # Reddit r/aviation and r/awardtravel used to be seeded here. Removed on the
    # owner's explicit instruction: community chatter surfaced as news (a photo
    # caption -- "NARLY 62 cruising down the Hudson corridor" -- and personal
    # award-booking questions) and as competitor campaigns (a stranger asking
    # about SFO-DEL award availability, filed as a fare sale). Removing a source
    # from this list deactivates it in the live database on the next
    # ensure_seeded() reconcile -- see app/repositories/source_repository.py --
    # so this line is the whole fix, not just documentation of one.
    #
    # r/TurkishAirlines stays: it feeds BİZ's customer-voice channel
    # (app/ingest/tk_reviews_live.py), a deliberately different use of Reddit
    # from "treat it as a news source", and is not seeded here at all.
    #
    # Round 10: removing the seeds turned out to be half the fix. Reddit kept
    # arriving as *items inside the Google News radars* below, because
    # reddit.com ranks for consumer-travel phrases and Google News hands back
    # whatever ranked. app/ingest/blacklist.py now drops those at ingest, so
    # this list and the item filter enforce the same ban from both ends.
    # Google News topic radars: keyless aggregator RSS scoped to the newspaper's
    # focus areas (RM / pricing / NDC / ancillary / demand) and the user's main
    # rivals. Trust sits low because items come from arbitrary publishers; our
    # own dedupe + confidence scoring does the vetting.
    SourceSeed(
        "Google News · Revenue Management",
        "https://news.google.com/rss/search?q=airline%20%22revenue%20management%22%20OR%20%22yield%20management%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Fiyatlandırma",
        "https://news.google.com/rss/search?q=airline%20pricing%20OR%20airfares&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · NDC & Dağıtım",
        "https://news.google.com/rss/search?q=airline%20NDC%20OR%20%22airline%20distribution%22%20OR%20GDS&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Ek Gelir",
        "https://news.google.com/rss/search?q=airline%20%22ancillary%20revenue%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Talep & Kapasite",
        "https://news.google.com/rss/search?q=airline%20%22load%20factor%22%20OR%20%22capacity%20growth%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Ana Rakipler",
        "https://news.google.com/rss/search?q=%22Emirates%22%20OR%20%22Qatar%20Airways%22%20OR%20%22Etihad%22%20OR%20%22Lufthansa%22%20OR%20%22Air%20France%22%20OR%20%22KLM%22%20OR%20%22British%20Airways%22%20OR%20%22Pegasus%20Airlines%22%20OR%20%22AJet%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # Round 6, both verified live 2026-07-19 (100 items each):
    # TK radar feeds the BİZ page's news stream; the promo radar is the
    # *ongoing* source of rival campaign news (promos_seed.py is only a
    # point-in-time snapshot -- airline offer pages themselves are
    # bot-protected and can't be polled).
    SourceSeed(
        "Google News · Türk Hava Yolları",
        "https://news.google.com/rss/search?q=%22Turkish%20Airlines%22%20OR%20%22T%C3%BCrk%20Hava%20Yollar%C4%B1%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Rakip Kampanyalar",
        "https://news.google.com/rss/search?q=(%22Emirates%22%20OR%20%22Qatar%20Airways%22%20OR%20%22Lufthansa%22%20OR%20%22Air%20France%22%20OR%20%22British%20Airways%22%20OR%20%22Etihad%22%20OR%20%22KLM%22%20OR%20%22Pegasus%20Airlines%22%20OR%20%22AJet%22)%20(%22fare%20sale%22%20OR%20%22promotion%22%20OR%20%22discount%22%20OR%20%22flash%20sale%22)&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # Round-7 radars: seven focus areas the publisher desks under-cover. Volume
    # is bounded by AGGREGATOR_ITEM_CAP in app/ingest/rss.py (40 items/run) and
    # the relevance gate, so these widen recall without flooding the LLM stage.
    SourceSeed(
        "Google News · Bagaj & Ek Ücretler",
        "https://news.google.com/rss/search?q=airline%20%22baggage%20fee%22%20OR%20%22seat%20selection%20fee%22%20OR%20%22checked%20bag%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Sadakat Programları",
        "https://news.google.com/rss/search?q=airline%20%22loyalty%20program%22%20OR%20%22frequent%20flyer%22%20OR%20%22award%20miles%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · İttifak & Ortak Uçuş",
        "https://news.google.com/rss/search?q=airline%20codeshare%20OR%20%22joint%20venture%22%20OR%20%22Star%20Alliance%22%20OR%20oneworld%20OR%20SkyTeam&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Kapasite Kesintileri",
        "https://news.google.com/rss/search?q=airline%20%22capacity%20cuts%22%20OR%20%22route%20suspension%22%20OR%20%22cancels%20route%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Dinamik Fiyatlama",
        "https://news.google.com/rss/search?q=airline%20%22dynamic%20pricing%22%20OR%20%22continuous%20pricing%22%20OR%20%22offer%20and%20order%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "other", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Slot & Hub",
        "https://news.google.com/rss/search?q=%22airport%20slots%22%20OR%20%22slot%20allocation%22%20OR%20%22hub%20expansion%22%20airline&hl=en-US&gl=US&ceid=US:en",
        "rss", "airport", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · İstanbul Havalimanları",
        "https://news.google.com/rss/search?q=%22Istanbul%20Airport%22%20OR%20%22Sabiha%20G%C3%B6k%C3%A7en%22%20OR%20%22DHM%C4%B0%22&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airport", 0.5, tier="aggregator", language="tr",
    ),
    # ---------------------------------------------------------------------
    # Round-8: Turkish-language desks. Until now the only TR-native input was
    # one Google News radar, so domestic stories arrived second-hand (or in
    # English, days late) and the translation stage had nothing to do. Every
    # URL below was fetched live at build time and kept only on HTTP 200 +
    # real feed XML + at least one dated item; the failures are written up in
    # the DROPPED_CANDIDATES block below.
    # ---------------------------------------------------------------------
    # Dedicated aviation trade press.
    # Havayolu 101 is the pick of the set: it runs actual revenue-management
    # analysis (yield, load factor, fare structure) rather than reprinted
    # press releases, which is why it outranks every other TR source here.
    SourceSeed("Havayolu 101", "https://www.havayolu101.com/feed/", "rss", "other", 0.75, language="tr"),
    SourceSeed("AirlineHaber", "https://www.airlinehaber.com/feed/", "rss", "other", 0.65, language="tr"),
    SourceSeed("AirTürkHaber", "https://www.airturkhaber.com/feed/", "rss", "other", 0.6, language="tr"),
    # NOTE: this is the airporthaber2.com mirror on purpose. The main
    # airporthaber.com domain appears to geo-block non-Turkish egress IPs --
    # connection refused on every attempt from our egress, while the mirror
    # serves the same publication fine. If ingestion from this source ever
    # stops, re-test the primary domain before assuming the desk went dark.
    # Highest-volume TR aviation desk at ~10-15 items/day.
    SourceSeed("AirportHaber", "https://www.airporthaber2.com/rss/", "rss", "other", 0.6, language="tr"),
    # Press-release republisher, so trust sits low -- it rewrites carrier PR
    # rather than reporting it out. Kept anyway because it is the earliest and
    # most reliable TR signal for airline CAMPAIGN announcements (kampanya /
    # indirim), which is exactly what the promo tracking needs and what the
    # bot-walled carrier offer pages cannot give us.
    SourceSeed("Air News Times", "https://www.airnewstimes.com/feed/", "rss", "other", 0.45, language="tr"),
    # NOTE: this feed declares encoding="windows-1254", not UTF-8, and serves
    # it as `text/xml` with no charset parameter. It is safe: RssSourceAdapter
    # hands feedparser `response.content` (bytes), and feedparser reads the
    # charset off the XML declaration -- verified end to end, Turkish
    # characters land correctly ("THY TEKNİK'TEN YENİ HANGAR"). See the
    # matching comment in app/ingest/rss.py; that bytes-not-str detail is the
    # only thing standing between this source and mojibake.
    SourceSeed("Airkule", "https://www.airkule.com/sondakika.xml", "rss", "other", 0.55, language="tr"),
    # Mixed civil/defence, roughly weekly -- lowest priority of the TR set.
    SourceSeed("Kokpit.Aero", "https://kokpit.aero/feed/", "rss", "other", 0.55, language="tr"),
    # Adjacent desks: not aviation trade press, but the best TR sources for the
    # Etkinlik beat (congresses, festivals, sports) and for the demand-side
    # context a revenue-management desk reads underneath a fare move.
    # AA is a national wire -- authoritative, hence the high trust -- but this
    # is the general *economy* feed, so most items are not aviation at all. It
    # is not capped by AGGREGATOR_ITEM_CAP (that only triggers on
    # news.google.com URLs) and at 30 items/run it does not need to be; the
    # relevance gate in the enrichment pipeline is the right filter here,
    # since the problem is topicality, not volume.
    SourceSeed(
        "Anadolu Ajansı · Ekonomi", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
        "rss", "org", 0.85, tier="agency", language="tr",
    ),
    SourceSeed("Turizm Günlüğü", "https://www.turizmgunlugu.com/feed/", "rss", "other", 0.6, language="tr"),
    # Small volume, analytical -- demand and market-shift pieces.
    SourceSeed("Turizm DataBank", "https://www.turizmdatabank.com/feed/", "rss", "other", 0.6, language="tr"),
    # ---------------------------------------------------------------------
    # Round-9: fare-campaign radars. Every desk above is a general aviation
    # desk that happens to mention a sale now and then; these were selected
    # the other way round -- fetched live on 2026-08-30, then *sampled*, and
    # kept only when the majority of recent items were actual fare campaigns
    # (a sale, a discount, a booking window) rather than loyalty news, fleet
    # news or product launches. The measured ratio is recorded per source
    # below, because it is the number that decides whether a feed is earning
    # its place in the enrichment budget, and it is the number nobody can
    # reconstruct six months from now without re-doing the sampling.
    #
    # These flow through the existing article pipeline (ingest -> enrich ->
    # pipeline/promotions.py). They are the *corroboration* half of campaign
    # detection: the carrier pages in app/ingest/carriers.py are the official
    # statement, and a trade desk reporting the same sale is the second source
    # that promo_dedup.rescore_for_corroboration counts.
    #
    # NOTE on the Google News queries: news.google.com answers HTTP 400 to a
    # raw non-ASCII `q`. Every query below is percent-encoded for that reason,
    # not for tidiness -- decoding one "to make it readable" breaks the feed.
    # ---------------------------------------------------------------------
    # Turkish carrier campaign radars. ~95% / ~100% / ~90% fare content in the
    # 2026-08-30 sample -- by a distance the densest campaign sources this
    # product has, because a Turkish "kampanya" headline is almost always a
    # fare sale rather than a loyalty promotion.
    SourceSeed(
        "Google News · AJet Kampanya",
        "https://news.google.com/rss/search?q=AJet+kampanya&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airline", 0.5, tier="aggregator", language="tr",
    ),
    SourceSeed(
        "Google News · Pegasus Kampanya",
        "https://news.google.com/rss/search?q=Pegasus+kampanya+bilet&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airline", 0.5, tier="aggregator", language="tr",
    ),
    SourceSeed(
        "Google News · THY Kampanya",
        "https://news.google.com/rss/search?q=%22THY%22+kampanya&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airline", 0.5, tier="aggregator", language="tr",
    ),
    # Turkish aviation desks, queried for campaigns rather than read whole.
    # WordPress's `?s=<term>&feed=rss2` search feed is the mechanism: it turns
    # a general desk into a campaign radar without adding its whole output to
    # the ingest budget. AirlineHaber and Air News Times are already seeded
    # above as full feeds; these are the *campaign* slices of the same desks,
    # which is why both entries can coexist -- the dedupe layer collapses an
    # item that arrives through both.
    # ~80% / ~80% / ~60% fare content, sampled 2026-08-30.
    SourceSeed(
        "Hava Sosyal Medya · Kampanya",
        "https://havasosyalmedya.com/?s=kampanya&feed=rss2",
        "rss", "other", 0.55, language="tr",
    ),
    SourceSeed(
        "AirlineHaber · Kampanya",
        "https://www.airlinehaber.com/?s=kampanya&feed=rss2",
        "rss", "other", 0.6, language="tr",
    ),
    SourceSeed(
        "Air News Times · Kampanya",
        "https://www.airnewstimes.com/?s=kampanya&feed=rss2",
        "rss", "other", 0.45, language="tr",
    ),
    # Gulf-carrier sale coverage. Live and Let's Fly, Head for Points, One Mile
    # at a Time and View from the Wing were all sampled for this beat and
    # rejected at 97-100% loyalty content -- award charts and status runs, not
    # fares. Live from a Lounge is the one that came back the other way: ~80%
    # fare content, with Etihad and Qatar sale windows in the headlines
    # themselves, which is exactly what pipeline/promotions.py reads.
    SourceSeed(
        "Live from a Lounge · Sale Fares",
        "https://livefromalounge.com/?s=sale+fares&feed=rss2",
        "rss", "airline", 0.55,
    ),
    # English-language carrier radars. Lower ratios and lower trust to match:
    # the Etihad query samples ~75%, and the Qatar one ~50% because
    # "Qatar Airways sale" is a promo-code SEO term and half the results are
    # coupon-farm rewrites. Kept because the relevance gate and the confidence
    # scorer are the right filters for that, and because QR/EY are the two
    # carriers whose own pages this product still cannot read without a
    # browser.
    SourceSeed(
        "Google News · Etihad Flash Sale",
        "https://news.google.com/rss/search?q=%22Etihad%22+flash+sale&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    SourceSeed(
        "Google News · Qatar Airways Sale Fares",
        "https://news.google.com/rss/search?q=%22Qatar+Airways%22+sale+fares&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.45, tier="aggregator",
    ),
    # ---------------------------------------------------------------------
    # Round-10: the rest of the tracked carriers, plus generic fare-sale
    # radars. Round 9 left five of the tracked carriers without a campaign
    # query of their own and had no language coverage outside TR/EN at all,
    # which is why "hala çok az kampanya tespit ediliyor" survived it: a
    # Turkish desk does not report a KLM sale and an English desk does not
    # report an Air France one.
    #
    # Same bar as round 9, re-applied: fetched live on 2026-08-31, HTTP 200,
    # >= 5 items, then the newest ~20 headlines read one by one and scored for
    # actual fare-campaign content (a sale, a discount, a booking window) as
    # opposed to loyalty/award news, route launches or product reviews. The
    # measured ratio is recorded per source. Anything under ~50% was rejected
    # and written up in DROPPED_CANDIDATES -- five candidates were, including
    # both Lufthansa attempts and the Dutch KLM one, so this list is shorter
    # than the carrier roster on purpose.
    #
    # Budget note: everything here flows through the existing relevance gate
    # (PROMO_WITH_AVIATION_BONUS) and then the business-class rulepacks, so
    # loyalty and product junk that slips past the query is still filtered
    # after ingest. That is a safety net, not a licence -- precision at the
    # query level is what keeps the LLM stage affordable, which is why the
    # ratio above is measured rather than assumed.
    #
    # Percent-encoding: same rule as round 9 and now load-bearing in four more
    # scripts. news.google.com answers HTTP 400 to a raw non-ASCII `q`, so the
    # Turkish, German and Arabic queries below MUST stay encoded.
    # ---------------------------------------------------------------------
    # Per-carrier radars for the tracked carriers round 9 missed.
    # ~95% fare content -- the densest English-language carrier radar in the
    # list. The trick is the exact phrases: Emirates PR says "special fares",
    # and quoting it excludes the NerdWallet/Simple Flying explainer genre that
    # sank the looser "Emirates flight sale fares" attempt (~35%, dropped).
    SourceSeed(
        "Google News · Emirates Special Fares",
        "https://news.google.com/rss/search?q=%22Emirates%22%20%22flight%20sale%22%20OR%20%22special%20fares%22%20OR%20%22fare%20sale%22&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # ~95% fare content. SIA runs named, dated public sales ("Time To Fly",
    # "Global Fare Sale") and the Singapore consumer desks cover every one of
    # them with the fare and the booking deadline in the headline.
    SourceSeed(
        "Google News · Singapore Airlines Promo Fares",
        "https://news.google.com/rss/search?q=%22Singapore%20Airlines%22%20promotion%20fares%20OR%20%22promo%20fares%22&hl=en-SG&gl=SG&ceid=SG:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # ~85% fare content, and the only French-language input this product has.
    # Note it catches Transavia and KLM alongside AF, because the French press
    # reports the group's seasonal promos as one story -- which is also the
    # closest thing to KLM campaign coverage that survived verification.
    SourceSeed(
        "Google News · Air France Promotions",
        "https://news.google.com/rss/search?q=%22Air%20France%22%20promotion%20vols%20OR%20%22billets%20pas%20chers%22&hl=fr&gl=FR&ceid=FR:fr",
        "rss", "airline", 0.5, tier="aggregator", language="fr",
    ),
    # ~75% fare content. Unusual shape: over half the items are BA's own media
    # centre, so this radar is effectively an official-announcement feed for a
    # carrier that publishes no RSS -- it stays tier="aggregator" because that
    # is how it arrives and what the confidence scorer should assume, but it is
    # the reason the trust weight sits at the top of the aggregator band.
    SourceSeed(
        "Google News · British Airways Sale Fares",
        "https://news.google.com/rss/search?q=%22British%20Airways%22%20sale%20fares&hl=en-GB&gl=GB&ceid=GB:en",
        "rss", "airline", 0.55, tier="aggregator",
    ),
    # ~70% fare content. TK's own campaigns already arrive in Turkish at ~95%
    # (the THY radar above); this is the outbound half -- the US/Canada sales
    # the Turkish desks do not cover, which are the ones a rival's revenue
    # desk would actually be watching.
    SourceSeed(
        "Google News · Turkish Airlines Sale Fares",
        "https://news.google.com/rss/search?q=%22Turkish%20Airlines%22%20sale%20OR%20promotion%20fares&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # ~78% fare content but only 9 items in the whole feed -- AJet is barely
    # covered in English and one publisher (turkiyetoday.com) writes most of
    # it. Kept because the density is real and the cost of a nine-item feed is
    # nil; re-check it rather than trusting it if AJet coverage ever matters
    # more than it does today.
    SourceSeed(
        "Google News · AJet Sale Fares",
        "https://news.google.com/rss/search?q=%22AJet%22%20sale%20OR%20promotion%20fares&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.5, tier="aggregator",
    ),
    # Generic fare-sale radars -- four, not one per carrier. A carrier query
    # only finds a sale once someone names the carrier; these catch the sale
    # itself, including from carriers nobody thought to track, and they are the
    # cheapest way to widen recall without another twenty seeds.
    # ~100% fare content, 100 items, and every single sampled headline was a
    # Turkish carrier campaign with the price in it. The best feed in this
    # file by density, national desks included (AA, NTV, CNN Türk, Milliyet).
    SourceSeed(
        "Google News · Uçak Bileti Kampanya",
        "https://news.google.com/rss/search?q=u%C3%A7ak%20bileti%20kampanya%20indirim&hl=tr&gl=TR&ceid=TR:tr",
        "rss", "airline", 0.5, tier="aggregator", language="tr",
    ),
    # ~100% fare content. Covers the Gulf carriers in their home market, where
    # QR/EK/EY announce discounts that the English-language desks pick up days
    # later or not at all -- plus Saudia, flynas and EgyptAir, which no other
    # feed in this file reaches. First Arabic-language source in the product.
    SourceSeed(
        "Google News · عروض طيران (Körfez Kampanyaları)",
        "https://news.google.com/rss/search?q=%D8%B9%D8%B1%D9%88%D8%B6%20%D8%B7%D9%8A%D8%B1%D8%A7%D9%86%20%D8%AA%D8%B0%D8%A7%D9%83%D8%B1%20%D8%AE%D8%B5%D9%85&hl=ar&gl=SA&ceid=SA:ar",
        "rss", "airline", 0.5, tier="aggregator", language="ar",
    ),
    # ~80% fare content, 100 items. Carrier-agnostic by design: the sampled
    # items were mostly Philippine Airlines and the US low-cost carriers, i.e.
    # not the tracked roster -- that is the point of a generic radar, and the
    # relevance gate is what decides whether an untracked carrier's flash sale
    # is worth an enrichment call.
    SourceSeed(
        "Google News · Flash Sale Radarı",
        "https://news.google.com/rss/search?q=airline%20%22flash%20sale%22%20fares&hl=en-US&gl=US&ceid=US:en",
        "rss", "airline", 0.45, tier="aggregator",
    ),
    # ~63% fare content -- the weakest feed added this round, and the second
    # German query tried: "Flugangebote Sale OR Aktion" returned nine items at
    # ~55%, and the plain "Lufthansa Angebot" shape was a disaster (see
    # DROPPED_CANDIDATES). Kept at a lower trust weight because German fare
    # coverage is dominated by loyalty blogs and this is the only wording that
    # reached the majority bar; it is the only German input the product has.
    SourceSeed(
        "Google News · Flugtickets Rabattaktion",
        "https://news.google.com/rss/search?q=Airline%20Rabattaktion%20OR%20Sonderangebot%20Flugtickets%20g%C3%BCnstig&hl=de&gl=DE&ceid=DE:de",
        "rss", "airline", 0.4, tier="aggregator", language="de",
    ),
    # ---------------------------------------------------------------------
    # Round-11: the two tiers this file was thinnest in. Before this round the
    # `official` tier held exactly ONE source (Delta News Hub) and the only
    # Turkish institution of any kind was Anadolu Ajansı's general economy
    # feed -- so a national regulator changing what carriers may legally do
    # reached this newspaper, if at all, as a trade-press rewrite days later.
    #
    # Same bar as rounds 7-10, re-applied on 2026-09-02 with the application's
    # own User-Agent and feedparser.parse(response.content) -- i.e. the exact
    # path RssSourceAdapter takes, not curl -- and the measurement recorded per
    # source below.
    # ---------------------------------------------------------------------
    # SHGM (Turkish DGCA). Not findable by convention: every guessable path
    # (/tr/rss, /rss) soft-404s -- HTTP 200 with a "404 Page Not Found" HTML
    # body, which is exactly the trap the round-8 note about SHGM in
    # DROPPED_CANDIDATES describes. The working endpoint is rss.php with the
    # section as a bare query string, linked only from /tr/kurumsal/4000-rss.
    #
    # Three section feeds, NOT the four that exist: the site also serves
    # `rss.php?tr` ("Tümü"), and it was measured to be the exact union of these
    # three -- 45 items, 45 unique links, every one of them present in a
    # section feed and no section item missing from it. Seeding it alongside
    # would double every SHGM fetch for zero new items, and worse, would
    # destroy the per-section attribution this split exists for: ingestion
    # dedupes on URL first-writer-wins, so a Mevzuat item that arrived through
    # "Tümü" first would be filed under the generic source and lose the
    # regulator weighting below. See DROPPED_CANDIDATES.
    #
    # Turkish only -- the ?en variants 404.
    #
    # The highest-value feed of the three, and the reason this block exists:
    # SHT/SHY instruction revisions are the primary legal text, not a report
    # about one. Sampled 2026-09-02, 15 items: "Onaylı Tedarikçi Kuruluşları
    # Talimatı Rev.01", "Hava Aracı Bakım Lisansı Talimatı (SHT-66) ... 01
    # numaralı revizyonu", "Küresel Raporlama Formatı (GRF) Talimatı".
    # priority is elevated by hand rather than derived: a regulator feed whose
    # items change what carriers may legally do outranks the rest of its tier.
    SourceSeed(
        "SHGM · Mevzuat", "https://web.shgm.gov.tr/rss.php?tr/mevzuat",
        "rss", "org", 0.92, tier="regulator", language="tr",
        priority="very_high", news_categories="regulatory,safety",
        crawl_frequency_minutes=720,
    ),
    # 15 items. Official announcements rather than legal instruments -- fee
    # tariff updates, medical-certificate rules, licensing notices. Sampled:
    # "SHGM 2026 Yılı Hizmet Tarifesi'nde güncelleme", "2026-YKS Havacılık
    # Programlarına Yerleşen Adayların Sağlık Belgeleri". Overlaps Mevzuat by
    # design at SHGM's end: an instruction is published under both sections
    # with two different URLs, so URL dedupe does NOT collapse it. That is the
    # publisher's doing, not this seeding's, and it costs one duplicate row per
    # cross-posted instruction.
    SourceSeed(
        "SHGM · Duyurular", "https://web.shgm.gov.tr/rss.php?tr/duyurular",
        "rss", "org", 0.90, tier="regulator", language="tr",
        priority="high", news_categories="regulatory,labor,finance",
        crawl_frequency_minutes=720,
    ),
    # 15 items, and the softest of the three -- the authority's own news desk,
    # so bilateral-agreement signings and conference readouts sit next to real
    # policy. Sampled: "Pilot Uçuş Kayıt Defterinde Dijital Dönem", "Türkiye
    # ile Kazakistan Arasında Havacılık Alanında Yeni Mutabakat Zaptı".
    # Trust and priority both step down accordingly: institutional PR is not
    # the same claim as an instruction revision, and the tier alone would have
    # said it was.
    SourceSeed(
        "SHGM · Haberler", "https://web.shgm.gov.tr/rss.php?tr/haberler",
        "rss", "org", 0.85, tier="regulator", language="tr",
        priority="normal", news_categories="regulatory,network,general",
        crawl_frequency_minutes=720,
    ),
    # Only the SECOND source in the `official` tier, after Delta News Hub, and
    # the first European one. Note the URL: the round-7 attempt at Lufthansa
    # (newsroom.lufthansagroup.com/en/rss/all.xml, 404 -- still listed in
    # DROPPED_CANDIDATES) failed on the path, not on the publisher. /feed/en
    # answers 200 application/xml, RSS 2.0, 25 items.
    #
    # Density measured by reading all 25 headlines on 2026-09-02: 9 are
    # commercially relevant to an RM desk (36%) -- the H1 result with demand
    # and fuel cost, the TAP Air Portugal minority-stake bid, the ANA/ITA
    # Europe-Japan joint venture, Asiana leaving Star Alliance, the Miles &
    # More consolidation, the Allegris route launches, the summer fare push,
    # the APAC stopover product and the Indian transit-visa change.
    #
    # The other 64% is worth naming because it is PREDICTABLE, which is what
    # makes it cheap for the relevance gate rather than a reason to reject the
    # feed: Lufthansa Technik MRO facility announcements, Starlink
    # connectivity, SAF/AeroSHARK sustainability, executive appointments, and
    # ceremonial PR (anniversaries, liveries, sponsored flights). A carrier
    # newsroom mixing its own hard commercial news with its own PR is the
    # normal shape of an official feed; the alternative was continuing to read
    # LH secondhand.
    SourceSeed(
        "Lufthansa Group Newsroom", "https://newsroom.lufthansagroup.com/feed/en",
        "rss", "airline", 0.9, tier="official",
        priority="high", news_categories="network,revenue_management,finance,fleet",
        crawl_frequency_minutes=360,
    ),
    # PROS was a premium stub until this round -- listed as an unreachable
    # commercial RM platform. It publishes a real, open RSS feed, so the stub
    # has been removed from PREMIUM_SOURCE_NAMES below and replaced by this.
    # Removing the old "PROS" name from the seed list deactivates that row on
    # the next ensure_seeded() reconcile, which is the intended retirement
    # path (see app/repositories/source_repository.py).
    #
    # 10 items, HTTP 200, RSS 2.0. The densest RM-vocabulary feed in this file:
    # 7 of 10 headlines are offer-and-order / continuous-pricing / airline
    # retail material -- "From PSS to Offer & Order", "Modern Airline Retail: A
    # Practical Roadmap to Offer Management", "Commercial Agility Starts with
    # the Offer". The other 3 are SEO/GEO content-marketing pieces.
    #
    # It is a vendor blog and is weighted as one: 0.75 and tier="trade", not
    # "official", because PROS is not the actor in the stories it tells. What
    # it is good for is vocabulary and direction of travel in the exact
    # discipline this newspaper covers -- and, in passing, which carriers are
    # deploying what.
    SourceSeed(
        "PROS Blog", "https://pros.com/learn/blog/feed/",
        "rss", "financial", 0.75, tier="trade",
        priority="high", news_categories="revenue_management",
        crawl_frequency_minutes=720,
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
# Turkish candidates (round 8). Note the first two: both return HTTP 200 and
# perfectly valid RSS, so a reachability check passes and only the item DATES
# reveal that nobody is home. Check freshness, not just status codes.
#   havayolufirsatlari.com  feeds.feedburner.com/havayolufirsatlari  200, 100 valid items, newest
#                                                                   2025-02-20 -- abandoned. The
#                                                                   content is ideal (TR promo/fare
#                                                                   deals); the desk is dead. A trap.
#   tayyareci.com         https://www.tayyareci.com/feed/           200, valid, but 2 items and
#                                                                   newest 2024-08-27 -- an archive
#   aviationturkey.com    /feed/, /rss, /feed.xml                   200 + text/html on every path
#                                                                   (React SPA shell, 0 entries)
#   DHMİ                  no feed published (HTML newsroom only)
#   SHGM                  https://web.shgm.gov.tr/tr/rss            200 but the BODY is a 404 page
#                                                                   (text/html) -- status code lies
#   THY / Pegasus / AJet  no RSS at all. Their campaign pages are read directly instead --
#                         see app/ingest/carriers.py, which as of round 9 reaches all three.
# Fare-deal candidates sampled at round 9 (2026-08-30) and dropped:
#   secretflying.com/feed           403 (Cloudflare)
#   executivetraveller.com/feed     403 (Cloudflare)
#   ucuzabilet.com/blog/feed        403 (Cloudflare)
#   Head for Points                 200, real feed, ~100% loyalty content -- Avios and status,
#                                   not fares. Rejected on content, not reachability.
#   One Mile at a Time / Live and Let's Fly (already seeded above as general desks)
#                                   sampled at ~97% loyalty for the fare beat; kept where they
#                                   are, not promoted into the campaign radars.
#   Simple Flying / AeroTime / AirlineGeeks  ~0% fare-campaign content when sampled for it.
#   Lufthansa, KLM English RSS      0 bytes. The endpoint answers, with nothing in it.
# Round-10 campaign-radar candidates (sampled 2026-08-31). All eight returned
# HTTP 200 and a valid feed -- every rejection below is on CONTENT, at the
# ~50% fare-campaign bar, which is the bar worth re-reading before anyone
# "fixes the gap" by re-adding one of them:
#   "Lufthansa Angebot OR Sparangebot Flug" (de)   ~5%. The trap is the word: German
#                                   "Angebot" means supply as much as offer, so the feed
#                                   came back as capacity news -- "Lufthansa reduziert
#                                   Angebot nach New York", "streicht 20.000 Flüge".
#                                   Correct German, wrong meaning.
#   "Lufthansa" fare sale OR promotion (en)        ~25%. Miles & More award charts and
#                                   Allegris cabin news, not fares.
#   Lufthansa Rabatt OR Aktion Flugtickets (de)    ~40%, and 50% outright loyalty --
#                                   meilenoptimieren.com alone wrote half the sample.
#                                   Third attempt at LH and the closest; still under
#                                   the bar. LH campaigns reach us only through the
#                                   multi-carrier "Rakip Kampanyalar" radar for now.
#   KLM aanbieding OR ticketactie vliegtickets (nl) ~15%. Dutch KLM coverage in the
#                                   sample window was labour disputes and strikes.
#                                   KL is instead partly covered by the French
#                                   Air France radar, which reports the group's
#                                   promos as one story.
#   "Pegasus Airlines" sale OR promotion fares (en) ~22%. Route launches plus Reuters
#                                   Middle-East cancellation factboxes. PC is already
#                                   at ~100% via "Pegasus kampanya bilet" (tr), so
#                                   this added nothing but volume.
#   "Emirates" flight sale fares (en)              ~35%, and Emirates airline sale
#                                   discount fares booking (en-AE) ~30% -- both drowned
#                                   in "Emirates Business Class: What to Know" explainers.
#                                   The quoted-phrase version above is what worked.
#   Flugangebote Sale OR Aktion Flugtickets (de)   ~55% but only 9 items, a third of
#                                   them loyalty. Superseded by the Rabattaktion query.
#   Fluggesellschaft Sparpreise OR Ticketaktion (de) 10 items, all ten Corendon press
#                                   releases from one publisher. Not a radar, a newsroom.
# Round-11 candidates, all probed on 2026-09-02 with the application's own
# User-Agent through httpx + feedparser (the RssSourceAdapter path). Five are
# unreachable and two were rejected on measurement despite working:
#   Business Travel News  /rss and even /robots.txt        403 on BOTH, with a Cloudflare
#                                                          "Just a moment..." managed-challenge
#                                                          body (~5.6 KB). robots.txt being
#                                                          behind the challenge too is the tell:
#                                                          there is no polite path in, so this
#                                                          is not a User-Agent problem to solve.
#   Amadeus blog          https://amadeus.com/en/blog/feed 200 + text/html, ~1 KB every time --
#                                                          an Imperva "Pardon Our Interruption"
#                                                          shell. Status code lies; see the stub
#                                                          comment in PREMIUM_SOURCE_NAMES.
#   Travolution           /rss/, /rss, /feed/              404 on all three (~21 KB branded
#                                                          "Not Found" page). The site is
#                                                          server-rendered and could be scraped
#                                                          one day; there is no feed to poll.
#   Turkish Airlines      press.turkishairlines.com        NXDOMAIN -- the press subdomain does
#                                                          not resolve at all. www does resolve
#                                                          (195.175.177.26) but hangs to a
#                                                          timeout on every path, which is the
#                                                          same TLS-fingerprint block AJet gives.
#   AJet                  https://www.ajet.com/rss         resolves (195.175.177.10), then
#                                                          ReadTimeout. Same block as THY.
#                                                          (Both remain covered by the Google
#                                                          News radars and app/ingest/carriers.py.)
#   SHGM "Tümü"           https://web.shgm.gov.tr/rss.php?tr  WORKS -- 200, RSS 2.0, 45 items.
#                                                          Rejected as pure redundancy: measured
#                                                          45 unique links, of which 45 also
#                                                          appear in the three section feeds, and
#                                                          0 section items are missing from it.
#                                                          Exactly Duyurular + Haberler + Mevzuat.
#                                                          Seeding it would double every SHGM
#                                                          fetch and, because ingest dedupes on
#                                                          URL first-writer-wins, would file
#                                                          Mevzuat items under a generic source
#                                                          and lose the regulator weighting the
#                                                          per-section split exists to give them.
#   PROS news (WP-JSON)   /wp-json/wp/v2/news?per_page=20  WORKS -- 200 application/json, 20
#                                                          items. Rejected on three counts, any
#                                                          one of which would do. (1) It is not
#                                                          RSS: _adapter_for() in
#                                                          services/ingestion_service.py knows
#                                                          "rss" and "premium", so this needs a
#                                                          whole JSON adapter. (2) Cadence: those
#                                                          20 items span 2025-07-10 to 2026-08-05
#                                                          -- thirteen months, ~1.5 items/month,
#                                                          newest already a month old at probe
#                                                          time. (3) Content: 4 of 20 are airline
#                                                          deployments (TAP continuous pricing,
#                                                          Cyprus Airways airTRFX, SriLankan,
#                                                          the LH Group renewal) = 20%. The rest
#                                                          is issuer PR -- the Thoma Bravo
#                                                          acquisition in three parts, quarterly
#                                                          results, a Stevie award, an SVP hire
#                                                          -- plus the SAME conference recap
#                                                          ("World Aviation Festival 2025 - Day 2
#                                                          Highlights") published three times.
#                                                          The blog covers the same beat at 70%
#                                                          through the existing adapter, so the
#                                                          new code would buy negative value.
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
    # Stays a stub, but for a sharper reason than "no public API": Amadeus
    # *does* run a blog, and it is unreadable. https://amadeus.com/en/blog/feed
    # answers HTTP 200 with `text/html` and ~1 KB of Imperva interstitial
    # ("Pardon Our Interruption", NOINDEX/NOFOLLOW) on every attempt -- a body
    # that can never parse as a feed however many times it is retried. Verified
    # 2026-09-02; do not re-add it as an RSS source on the strength of the 200.
    SourceSeed("Amadeus", "https://amadeus.com", "premium", "financial", 0.8, is_premium_stub=True),
    # PROS was here. It is now a real RSS source ("PROS Blog", round 11 above)
    # -- the stub was wrong about it, not merely incomplete.
    SourceSeed("Accelya", "https://www.accelya.com", "premium", "financial", 0.8, is_premium_stub=True),
    SourceSeed(
        "Lufthansa Systems", "https://www.lufthansa-systems.com", "premium", "financial", 0.8,
        is_premium_stub=True,
    ),
]

ALL_SOURCES: list[SourceSeed] = FREE_RSS_SOURCES + PREMIUM_SOURCE_NAMES
