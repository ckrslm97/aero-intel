"""The carrier master: which airlines we watch, where their campaigns live, and
how each page has to be fetched.

This is the spec's `carrier_master`, and it is deliberately data rather than
code. Adding an eighth carrier is adding an entry below -- no branch in
`deep_scan.py`, no new selector class, no new workflow. The scanner reads this
table and nothing else.

Two things are recorded per page that a bare URL list could not carry:

  * `fetch_method` -- how this carrier has to be reached. Four values, in
    ascending cost:

      `static`      a plain httpx GET works. Pegasus only.
      `api`         the carrier publishes structured JSON that answers without
                    a browser and without a wall: AJet's CMS gateway and
                    Singapore Airlines' fare-deal endpoint. Cheapest *and*
                    highest-fidelity -- no markup to parse and no prose to
                    interpret.
      `impersonate` an httpx GET is refused but a GET carrying Chrome's TLS
                    fingerprint is not. TK only, and it is the discovery this
                    file was rewritten for -- see below.
      `browser`     the page renders its offers client-side, so the bytes are
                    not enough even when they arrive. QR, EY, EK, BA.

    `deep_scan` runs the `api` and `impersonate` carriers first, in-process and
    without a browser, then drives Chromium for the rest. It still skips
    `static` entirely: `promo_scrape.py` already reads Pegasus with a parser
    tuned to its markup, and running it twice would be duplicate load on
    someone else's server for identical rows. Pegasus is listed anyway so this
    file is the single answer to "which carriers does this system watch?".
  * `block_selector` -- the CSS selector for the campaign cards, when we know
    it. It matters for change detection, not for parsing: hashing the campaign
    blocks instead of the whole page keeps a rotating hero banner or a footer
    cookie notice from reporting a change every single run and spending an LLM
    call on it. `None` means "we have not been able to look at this page's
    markup yet" -- the scanner then hashes the whole body, which is correct but
    noisier.
  * `api_url` -- the endpoint actually fetched, when it is not the page a human
    would open. AJet's campaigns are served by a CMS gateway on another host;
    `url` stays the page an analyst can click and `api_url` is what change
    detection keys on, because the honest answer to "what did we fetch?" is the
    endpoint.

**The wall was TLS, not the IP.** Every earlier note in this file and in
promo_scrape.py recorded TK/AJet/QR/EY as unreachable -- HTTP/2 stream reset,
HTTP/1.1 hang -- and concluded they fingerprint below the HTTP layer. That was
right about the layer and wrong about the consequence: it is a JA3/JA4 TLS
fingerprint check, and `curl_cffi` with Chrome's handshake gets HTTP 200 from
all four. See app/ingest/fetch.py for the measurement and for the caveat that
matters (all of it from a residential IP; Azure egress is what the scheduled
job's telemetry is actually testing).

**URL confidence is annotated per entry, and matters.** Each entry says whether
its URL is verified (a real Chromium reached it) or best-known (assembled from
the carrier's published URL pattern and not yet confirmable, because the wall
answers before the path is evaluated). Every entry below was run through
`deep_scan` from a Turkish residential IP while this file was written, and the
per-carrier result is recorded with it. That is one vantage point, not the
truth: the scheduled job runs from GitHub's Azure ranges, which these WAFs
score differently, so the workflow's own dry-run is still the gate. What the
local pass does establish is that the machinery works and that the walls are
real rather than a missing header.

**Newsroom tier.** `CarrierPage.kind` allows `newsroom`, which is the documented
fallback for a carrier that turns out to be permanently `blocked` on its
campaign page (press releases are usually served statically because carriers
want them indexed). No newsroom URL is listed yet on purpose: they would be
guesses, and a guessed URL that silently 404s twice a day is exactly the
"working coverage that returns zero rows forever" that promo_scrape.py refuses
to ship. They get added per carrier, verified, once the dry-run says that
carrier needs one.
"""
from dataclasses import dataclass

#: Every value `Carrier.fetch_method` may take. See the module docstring for
#: what each one costs and which carriers need it.
FETCH_METHODS: frozenset[str] = frozenset({"static", "api", "impersonate", "browser"})
#: The methods `deep_scan` reaches without a browser, in the order it runs them.
#: They are cheap httpx/curl_cffi calls, so they go first: a browser launch that
#: fails must not cost the carriers that never needed one.
DIRECT_FETCH_METHODS: tuple[str, ...] = ("api", "impersonate")
#: Every value `CarrierPage.kind` may take.
PAGE_KINDS: frozenset[str] = frozenset({"campaign", "newsroom"})


@dataclass(frozen=True)
class CarrierPage:
    """One page to fetch, plus the hints the fetch driver can use."""

    url: str
    kind: str = "campaign"
    #: CSS selector matching the campaign blocks. When set, only these blocks'
    #: text is hashed -- see the module docstring on why that is the point.
    block_selector: str | None = None
    #: CSS selector to wait for before reading the page, for carriers that
    #: render their campaign list client-side. `None` means domcontentloaded is
    #: taken as ready.
    wait_for: str | None = None
    #: The endpoint actually fetched, when it differs from `url`. See the
    #: module docstring; only the `api` carriers use it.
    api_url: str | None = None

    @property
    def fetch_url(self) -> str:
        """What is really requested, and what change detection keys on."""
        return self.api_url or self.url


@dataclass(frozen=True)
class Carrier:
    code: str
    display_name: str
    #: Key into app/llm/gazetteer.py AIRLINE_ALIASES, so a carrier scanned here
    #: and a carrier named in an article resolve to the same entity instead of
    #: two spellings of one airline. Checked against the gazetteer by test.
    alias: str
    pages: tuple[CarrierPage, ...]
    fetch_method: str
    #: ISO 639-1 of the page we fetch; also the browser context locale, because
    #: several of these sites serve different campaigns per Accept-Language.
    language: str
    #: Feeds pipeline/confidence.py. An airline's own campaign page is the most
    #: authoritative statement of its own sale window that exists, so these sit
    #: at or near 1.0 -- above any news report about the same campaign.
    source_quality: float


CARRIER_MASTER: dict[str, Carrier] = {
    # --- static ----------------------------------------------------------
    "PC": Carrier(
        code="PC",
        display_name="Pegasus Airlines",
        alias="pegasus",
        pages=(
            # VERIFIED: HTTP 200, server-rendered, and already parsed
            # field-by-field by app/ingest/promo_scrape.py. Listed for
            # completeness; deep_scan skips it (see module docstring).
            CarrierPage(
                url="https://www.flypgs.com/kampanyali-ucak-biletleri/aktif-kampanyalar",
                block_selector=".current-cmps-list__item",
            ),
        ),
        fetch_method="static",
        language="tr",
        source_quality=1.0,
    ),
    # --- api (structured JSON, no browser, no LLM) -----------------------
    "VF": Carrier(
        # IATA VF, matching gazetteer.AIRLINES; the brand is written "AJet"
        # everywhere the user sees it, which is what display_name carries.
        code="VF",
        display_name="AJet",
        alias="ajet",
        pages=(
            # VERIFIED, AND THE BEST SOURCE THIS PRODUCT HAS. ajet.com itself is
            # behind DataDome and stays behind it -- but the CMS gateway that
            # *feeds* ajet.com is not protected at all. A plain httpx POST, no
            # cookies, no impersonation, returns all 62 campaign records with
            # their ticketing window, travel window and detail link as separate
            # fields (see app/ingest/ajet_campaigns.py). Structured data beats a
            # parsed page and beats an LLM reading marketing prose, so this is
            # the one carrier whose campaigns cost no model call at all.
            #
            # `url` is the page a human opens -- and note it is
            # /tr/kesfet/kampanyalar/guncel-kampanyalar, not the /tr/kampanyalar
            # this file guessed at before: that path does not exist. Individual
            # campaigns carry their own detail URLs from the CMS.
            CarrierPage(
                url="https://www.ajet.com/tr/kesfet/kampanyalar/guncel-kampanyalar",
                api_url="https://gatewaycmsint.cloud.ajet.com/definition/Integration/getModelData",
            ),
        ),
        fetch_method="api",
        language="tr",
        source_quality=1.0,
    ),
    "SQ": Carrier(
        code="SQ",
        display_name="Singapore Airlines",
        alias="singapore airlines",
        pages=(
            # VERIFIED: HTTP 200, ~38KB of clean JSON, no wall of any kind.
            # This is a fare table rather than a campaign list -- lead-in "from"
            # prices per origin/destination/cabin, sourced from SQ's own fare
            # cache -- which is why app/ingest/sq_campaigns.py files every row
            # as EVERGREEN_OFFER and never as a dated campaign. Worth reading
            # anyway: an RM desk wants to know that SQ is selling MAN-SIN from
            # GBP 750 today, and this is the carrier stating it.
            #
            # `url` is the endpoint itself because SQ publishes no HTML deals
            # hub we could verify (/en_UK/gb/deals/ redirects to the homepage);
            # each fare deal's own `shareurl` is what the row links to instead.
            CarrierPage(
                url="https://www.singaporeair.com/home/getPromotions.form?locale=en_UK&country=GB",
            ),
        ),
        fetch_method="api",
        language="en",
        source_quality=1.0,
    ),
    # --- impersonate (Chrome TLS fingerprint, no browser) ----------------
    "TK": Carrier(
        code="TK",
        display_name="Turkish Airlines",
        alias="turkish airlines",
        pages=(
            # VERIFIED, and the reason FETCH_METHODS grew: HTTP 200, fully
            # server-rendered, via curl_cffi with impersonate="chrome". The
            # same URL from httpx or from headless Chromium is the documented
            # ERR_HTTP2_PROTOCOL_ERROR. The difference is the TLS handshake and
            # nothing else -- see app/ingest/fetch.py.
            #
            # The selector is TK's campaign card, read off the live page: each
            # `div.dinlinetable` carries an <h3> title, a <p> with both windows
            # in prose ("Biletinizi 30-31 Ağustos tarihlerinde alın, 24 Kasım
            # 2026-20 Ocak 2027 tarihleri arasında ... uçun.") and a detail
            # link. NOT `div.promotions`, which is the image sub-block inside
            # the card and contains no text -- see app/ingest/tk_campaigns.py.
            # Hashing the cards rather than the body keeps the rotating hero
            # and the fare-search widget from spending an LLM call twice a day.
            CarrierPage(
                url="https://www.turkishairlines.com/tr-tr/kampanyalar/",
                block_selector="div.dinlinetable",
            ),
            # /tr-tr/ucus-firsatlari/ was listed here and is gone on purpose: it
            # is the fare-search landing page, not the campaign list. The
            # campaign list is the URL above, and it is now readable -- keeping
            # a second page whose only content is a search widget would spend an
            # extraction call on hero copy every time the widget's defaults
            # moved.
        ),
        fetch_method="impersonate",
        language="tr",
        source_quality=1.0,
    ),
    # --- browser ---------------------------------------------------------
    "QR": Carrier(
        code="QR",
        display_name="Qatar Airways",
        alias="qatar airways",
        pages=(
            # VERIFIED URL, STILL browser: curl_cffi with a Chrome fingerprint
            # gets HTTP 200 from https://www.qatarairways.com/en/offers.html --
            # the 403 recorded here before was the TLS wall, not the path. But
            # the bytes that arrive carry no offers: the cards are rendered
            # client-side, so an impersonated GET returns a shell and would file
            # "QR has no campaigns" twice a day. The fingerprint problem and the
            # rendering problem are separate, and QR has both; the browser
            # solves the second one, which is the one that decides the rows.
            CarrierPage(url="https://www.qatarairways.com/en/offers.html"),
            # BEST-KNOWN, second shape: QR also publishes a `special-offers` hub
            # per locale. Cheap to keep both while we learn which one carries
            # the sale windows.
            CarrierPage(url="https://www.qatarairways.com/en-gb/special-offers.html"),
        ),
        fetch_method="browser",
        language="en",
        source_quality=1.0,
    ),
    "EK": Carrier(
        code="EK",
        display_name="Emirates",
        alias="emirates",
        pages=(
            # VERIFIED, AND THE ONE THAT WORKS: HTTP 200 in ~2.3s from headless
            # Chromium, 22 rendered offer cards. httpx gets 503 from this exact
            # URL, so Emirates is the carrier that proves the browser approach
            # is worth its cost rather than being an expensive way to collect
            # the same walls.
            #
            # Note `english`, not `turkish`: Emirates serves the Türkiye site in
            # English, and /tr/turkish/ is not the path in its own listings.
            #
            # The selector is the offer-card wrapper, read off the live page:
            # 22 blocks, each carrying the carrier label, the offer title, its
            # one-line description and -- the part worth hashing narrowly -- an
            # "Expires on 31 Aug 2026" line. The page's own "Last chance deals"
            # and "Recommended" carousels rotate independently of the offers,
            # so a whole-body hash here would report a change on most runs.
            CarrierPage(
                url="https://www.emirates.com/tr/english/special-offers/",
                block_selector=".special-offers-card__display__item-wrapper",
                wait_for=".special-offers-card__display__item-wrapper",
            ),
        ),
        fetch_method="browser",
        language="en",
        source_quality=1.0,
    ),
    "EY": Carrier(
        code="EY",
        display_name="Etihad Airways",
        alias="etihad airways",
        pages=(
            # VERIFIED URL, STILL browser -- exactly QR's situation. curl_cffi
            # gets HTTP 200 from https://www.etihad.com/en/offers (the
            # ERR_HTTP2_PROTOCOL_ERROR recorded here before was the TLS
            # fingerprint), and the offer cards are JS-rendered, so the bytes
            # alone are an empty page. The unprefixed /en/ path is what actually
            # answers; the /en-us/ guess is dropped.
            CarrierPage(url="https://www.etihad.com/en/offers"),
        ),
        fetch_method="browser",
        language="en",
        source_quality=1.0,
    ),
    "BA": Carrier(
        code="BA",
        display_name="British Airways",
        alias="british airways",
        pages=(
            # BEST-KNOWN, and TIMEOUT (measured): 30s with no response, on
            # most attempts. Twice out of six it instead answered 200 with a
            # ~20-word "We are experiencing high demand on ba.com at the
            # moment" holding page -- a queue, not the sale page. So BA is
            # intermittent rather than flatly walled, and neither shape yields
            # a campaign list: the hang hits the page cap, the holding page is
            # far below the minimum body length. Worth re-reading in the run
            # log after a few days rather than judging on one afternoon.
            #
            # The URL itself is the one BA's own press releases link to (and
            # /content/offers is the deals hub) -- not the /en-gb/ prefix the
            # booking flow uses.
            CarrierPage(url="https://www.britishairways.com/content/offers/sale"),
        ),
        fetch_method="browser",
        language="en",
        source_quality=1.0,
    ),
}


# ---------------------------------------------------------------------------
# DEAD ENDS. Every line below was fetched for real on 2026-08-30 and failed.
# They are written down so the next person does not spend an afternoon
# rediscovering them; do not re-add one without re-verifying it first.
#
# Carrier newsrooms -- the documented `newsroom` fallback in the module
# docstring turns out to have almost nothing behind it:
#   press.turkishairlines.com / news. / media.      NXDOMAIN (no such host)
#   press.ajet.com / news.ajet.com                  NXDOMAIN
#   press.qatarairways.com / news. / media.         NXDOMAIN
#   press.etihad.com / news.etihad.com              NXDOMAIN
#   qatarairways.mediaroom.com                      resolves, abandoned -- the
#                                                   newsroom is years stale
#   QR's live newsroom                              ~0% fare-campaign content;
#                                                   it is sponsorships and
#                                                   sustainability releases
#   blog.turkishairlines.com                        HTTP 403, even impersonated
#
# Carriers with no fetchable source at all today. Both are named in the spec
# and neither has one, which is a finding rather than a gap to paper over:
#   saudia.com (SV)    Imperva. AND THE TRAP: it answers HTTP **200** with a
#                      ~6183-byte challenge page. A naive status check calls
#                      this a success and files "SV has no campaigns" forever.
#                      deep_scan.detect_challenge catches it on body length,
#                      which is exactly why that check exists.
#   egyptair.com (MS)  Cloudflare challenge, impersonated or not.
#
# Third-party fare-deal feeds, all Cloudflare 403 on the feed URL:
#   secretflying.com, executivetraveller.com, ucuzabilet.com
#
# Carrier feeds that exist but are empty: Lufthansa and KLM publish no English
# RSS at all (0 bytes, not 404 -- the endpoint answers with nothing).
# ---------------------------------------------------------------------------


def browser_carriers() -> list[Carrier]:
    """The carriers deep_scan actually drives a browser for, in registry order."""
    return [c for c in CARRIER_MASTER.values() if c.fetch_method == "browser"]


def direct_carriers() -> list[Carrier]:
    """The carriers deep_scan reaches without a browser, in registry order.

    Run before the browser loop and in registry order, which puts the two
    `api` carriers ahead of the one `impersonate` carrier -- cheapest first, so
    a Chromium launch that fails on the runner still leaves this product with
    AJet's and SQ's campaigns.
    """
    return [c for c in CARRIER_MASTER.values() if c.fetch_method in DIRECT_FETCH_METHODS]


def resolve_carriers(codes: list[str] | None) -> list[Carrier]:
    """Registry entries for `codes`, or the whole registry when None.

    Accepts the IATA code or the display name, case-insensitively, because the
    brand and the code diverge for exactly the carrier a human is most likely
    to type by hand: `--carriers ajet` has to find VF.
    """
    if codes is None:
        return list(CARRIER_MASTER.values())

    by_name = {c.display_name.casefold(): c for c in CARRIER_MASTER.values()}
    resolved: list[Carrier] = []
    unknown: list[str] = []
    for raw in codes:
        key = raw.strip()
        if not key:
            continue
        carrier = CARRIER_MASTER.get(key.upper()) or by_name.get(key.casefold())
        if carrier is None:
            unknown.append(key)
        elif carrier not in resolved:
            resolved.append(carrier)

    if unknown:
        raise ValueError(
            f"Unknown carrier(s): {', '.join(unknown)}. "
            f"Known: {', '.join(CARRIER_MASTER)}"
        )
    return resolved
