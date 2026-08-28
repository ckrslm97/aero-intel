"""The carrier master: which airlines we watch, where their campaigns live, and
how each page has to be fetched.

This is the spec's `carrier_master`, and it is deliberately data rather than
code. Adding an eighth carrier is adding an entry below -- no branch in
`deep_scan.py`, no new selector class, no new workflow. The scanner reads this
table and nothing else.

Two things are recorded per page that a bare URL list could not carry:

  * `fetch_method` -- `static` or `browser`. Only Pegasus answers a plain httpx
    GET (verified live; see app/ingest/promo_scrape.py's docstring for the
    curl transcript). The other six reset the connection, hang, or serve a
    challenge page, so they need a real Chromium. `deep_scan` skips the static
    carriers entirely: `promo_scrape.py` already reads Pegasus properly, with a
    parser tuned to its markup, and running it twice would be duplicate load on
    someone else's server for identical rows. Pegasus is listed anyway so this
    file is the single answer to "which carriers does this system watch?".
  * `block_selector` -- the CSS selector for the campaign cards, when we know
    it. It matters for change detection, not for parsing: hashing the campaign
    blocks instead of the whole page keeps a rotating hero banner or a footer
    cookie notice from reporting a change every single run and spending an LLM
    call on it. `None` means "we have not been able to look at this page's
    markup yet" -- the scanner then hashes the whole body, which is correct but
    noisier.

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

#: Every value `Carrier.fetch_method` may take.
FETCH_METHODS: frozenset[str] = frozenset({"static", "browser"})
#: Every value `CarrierPage.kind` may take.
PAGE_KINDS: frozenset[str] = frozenset({"campaign", "newsroom"})


@dataclass(frozen=True)
class CarrierPage:
    """One page to fetch, plus the two hints the browser driver can use."""

    url: str
    kind: str = "campaign"
    #: CSS selector matching the campaign blocks. When set, only these blocks'
    #: text is hashed -- see the module docstring on why that is the point.
    block_selector: str | None = None
    #: CSS selector to wait for before reading the page, for carriers that
    #: render their campaign list client-side. `None` means domcontentloaded is
    #: taken as ready.
    wait_for: str | None = None


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
    # --- browser ---------------------------------------------------------
    "TK": Carrier(
        code="TK",
        display_name="Turkish Airlines",
        alias="turkish airlines",
        pages=(
            # BLOCKED (measured): net::ERR_HTTP2_PROTOCOL_ERROR from headless
            # Chromium -- the same HTTP/2 stream reset promo_scrape.py recorded
            # from httpx, on this same URL. Forcing HTTP/1.1 (--disable-http2)
            # reproduces the other half of that transcript exactly: the
            # connection is accepted and then never answered. A real browser is
            # not the missing piece; TK fingerprints below the HTTP layer.
            CarrierPage(url="https://www.turkishairlines.com/tr-tr/ucus-firsatlari/"),
            # BEST-KNOWN, same wall: TK's campaign hub is `/{locale}/kampanyalar/`
            # on the other locales (tr-int, and /campaigns/ on en-us, en-int),
            # so the tr-tr member of that family is where the Turkey-market
            # campaign list should be. Kept as a second page rather than
            # replacing the one above: they are not guaranteed to carry the
            # same offers, and the tr-tr list is the one this product is about.
            CarrierPage(url="https://www.turkishairlines.com/tr-tr/kampanyalar/"),
        ),
        fetch_method="browser",
        language="tr",
        source_quality=1.0,
    ),
    "VF": Carrier(
        # IATA VF, matching gazetteer.AIRLINES; the brand is written "AJet"
        # everywhere the user sees it, which is what display_name carries.
        code="VF",
        display_name="AJet",
        alias="ajet",
        pages=(
            # BLOCKED (measured): identical to TK, from a browser as from
            # httpx -- ERR_HTTP2_PROTOCOL_ERROR, and a hang when forced down to
            # HTTP/1.1. Unsurprising: AJet is TK's subsidiary and sits behind
            # the same edge.
            CarrierPage(url="https://www.ajet.com/tr/kampanyalar"),
        ),
        fetch_method="browser",
        language="tr",
        source_quality=1.0,
    ),
    "QR": Carrier(
        code="QR",
        display_name="Qatar Airways",
        alias="qatar airways",
        pages=(
            # BEST-KNOWN, and BLOCKED (measured): HTTP 403 with an "Access
            # Denied" body -- an edge WAF answering before the path is
            # evaluated, which is why neither of these URLs can be confirmed
            # correct from here. qatarairways.com scopes everything by locale
            # and the offers hub is `/{locale}/offers.html` (en-us and en-in
            # both publish a page titled "Explore our offers").
            CarrierPage(url="https://www.qatarairways.com/en-us/offers.html"),
            # BEST-KNOWN, second shape, same 403: QR also publishes a
            # `special-offers` hub per locale. Cheap to keep both while we
            # learn which one carries the sale windows.
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
            # BEST-KNOWN, and BLOCKED (measured): ERR_HTTP2_PROTOCOL_ERROR,
            # the TK/AJet signature again. etihad.com/en/offers redirects into
            # a locale and /en-us/offers is the locale that publishes "Flight
            # deals and special offers"; the locale form is used directly
            # rather than depending on a redirect nobody here can observe.
            CarrierPage(url="https://www.etihad.com/en-us/offers"),
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


def browser_carriers() -> list[Carrier]:
    """The carriers deep_scan actually drives a browser for, in registry order."""
    return [c for c in CARRIER_MASTER.values() if c.fetch_method == "browser"]


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
