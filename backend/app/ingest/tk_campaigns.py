"""Turkish Airlines' own campaign page, read without a browser.

https://www.turkishairlines.com/tr-tr/kampanyalar/ is server-rendered: the
campaign list is in the first response, not assembled by JavaScript afterwards.
That was never the problem. The problem was getting the first response at all,
and app/ingest/fetch.py explains what changed -- a Chrome TLS fingerprint, and
nothing else.

What the page gives us, per campaign card -- read off the live response rather
than guessed at, because the obvious guess is wrong:

    <div class="col-12 dtable dinlinetable">
      <div class="promotions">
        <img src="..."><a href="https://www.turkishairlines.com/tr-tr/ucus-firsatlari-...">
          Detaylı bilgi</a>
      </div>
      <h3>Zafer Bayramı'nda yurt içi uçuşlar 1.449 TL'den başlayan
          fiyatlarla!</h3>
      <p>Biletinizi 30-31 Ağustos tarihlerinde alın, 24 Kasım 2026-20 Ocak 2027
         tarihleri arasında ... uçun.</p>
    </div>

`div.promotions` is the *image and CTA* sub-block, not the card: it contains no
text at all, and selecting it yields eight empty divs and zero campaigns. The
card is `div.dinlinetable`, and the heading and paragraph are `.promotions`'s
siblings inside it. This is written down because the empty-selector failure
mode is silent -- eight matches, no titles, "TK has no campaigns" -- and
`campaign_text`'s body fallback is what would otherwise hide it.

The title carries the offer and the paragraph carries both windows in prose,
with the booking window and the travel window in one sentence. That is a
sentence, not a field: "Biletinizi ... alın, ... arasında ... uçun" has to be
read to know which of the two ranges is which. So TK -- unlike AJet and SQ,
whose CMS hands over labelled date fields -- goes through the LLM chain
(pipeline/campaign_extract.extract_campaigns_from_page), one call for the whole
page, exactly as the browser carriers do. The deterministic date layer then
re-reads every date the model returned out of this same text, so what gets
published is still regex-verified; the model's job here is only to say which
range is the booking one.

**Parsing is defensive by construction.** This is someone else's markup and it
will change without warning. A block with no heading is skipped rather than
inserted blank, and a selector that matches nothing falls back to the whole
body -- which is what lets `deep_scan.classify_outcome` tell a renamed CSS
class (parse_error) from a challenge page (blocked). The same fallback the
browser path has always had, for the same reason.

Known follow-up: each card carries its own `Detaylı bilgi` link, which is a
better row URL than the hub page plus a name fragment. It is parsed and logged
but not published, because the LLM path's idempotency key is
`campaign_extract.campaign_url(page_url, name)` by contract and threading a
per-campaign URL through the chain is a change to that contract rather than to
this file.
"""
from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.ingest.fetch import FetchResult, impersonated_get
from app.llm.gazetteer import fold_for_match

logger = get_logger(__name__)

SOURCE_NAME = "Turkish Airlines kampanya sayfası"

#: The campaign card wrapper -- NOT `div.promotions`, which is the image and
#: CTA inside it and carries no text; see the module docstring. Also declared
#: on the carrier entry (carriers.py, `block_selector`), which is what change
#: detection would read if TK ever went back to the browser path.
BLOCK_SELECTOR = "div.dinlinetable"
#: The card's own "Detaylı bilgi" link, inside the image sub-block.
DETAIL_LINK_SELECTOR = ".promotions a[href]"

#: Blocks whose subject is not a fare campaign, matched in folded space
#: (fold_for_match: lowercased, diacritics stripped, punctuation collapsed --
#: "Miles&Smiles" is "miles smiles" there).
#:
#: The rulepack in agents/campaign_airline.py rejects all of these anyway, so
#: this list changes no row. It changes what the page costs: TK's hub mixes
#: loyalty and holiday-package promotions in with the fare sales, and every one
#: of them that reaches the prompt is prompt budget spent on an item that will
#: be dropped two links later. Kept short and unambiguous for the reason
#: deep_scan's CHALLENGE_MARKERS are: a false positive here silently drops a
#: real campaign before anything can record that it existed.
OUT_OF_SCOPE_CUES: tuple[str, ...] = (
    "miles smiles",
    "milesandsmiles",
    "mil kazan",
    "mil harca",
    "holidays",
    "tatil paketi",
)


@dataclass(frozen=True)
class CampaignBlock:
    """One campaign card, reduced to what a reader of it would keep."""

    title: str
    body: str
    #: The card's "Detaylı bilgi" target. Parsed but not published yet -- see
    #: the module docstring's follow-up note.
    detail_url: str | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


def parse_campaign_blocks(html: str) -> list[CampaignBlock]:
    """The campaign cards, in page order. Never raises on bad markup."""
    soup = BeautifulSoup(html or "", "html.parser")
    blocks: list[CampaignBlock] = []

    for node in soup.select(BLOCK_SELECTOR):
        heading = node.find(["h3", "h2"])
        if heading is None:
            continue
        title = " ".join(heading.get_text(" ", strip=True).split())
        if not title:
            continue
        # Every paragraph in the card, not just the first: TK splits the
        # booking window and the travel window across two <p> often enough
        # that taking one would publish half the campaign.
        paragraphs = [
            " ".join(p.get_text(" ", strip=True).split())
            for p in node.find_all("p")
        ]
        body = " ".join(part for part in paragraphs if part)

        link = node.select_one(DETAIL_LINK_SELECTOR)
        href = link.get("href") if link is not None else None
        blocks.append(CampaignBlock(title=title, body=body, detail_url=href or None))

    return blocks


def out_of_scope_cue(block: CampaignBlock) -> str | None:
    """The phrase that makes this block not a fare campaign, or None."""
    folded = fold_for_match(block.text)
    for cue in OUT_OF_SCOPE_CUES:
        if cue in folded:
            return cue
    return None


def campaign_text(html: str) -> tuple[str, int, int]:
    """(text to hash and extract from, blocks found, blocks kept).

    The text is the kept blocks joined with blank lines. When the selector
    matches nothing at all the whole body is returned instead and the counts
    are zero -- see the module docstring on why that distinction has to survive
    to the classifier.
    """
    blocks = parse_campaign_blocks(html)
    if not blocks:
        soup = BeautifulSoup(html or "", "html.parser")
        return soup.get_text(" ", strip=True), 0, 0

    kept: list[CampaignBlock] = []
    for block in blocks:
        cue = out_of_scope_cue(block)
        if cue is not None:
            logger.info("tk_campaign_block_skipped", cue=cue, title=block.title[:120])
            continue
        kept.append(block)

    return "\n\n".join(block.text for block in kept), len(blocks), len(kept)


async def fetch_campaign_page(url: str, **kwargs) -> FetchResult:
    """Fetch the page and replace its HTML body with the campaign text.

    The `FetchResult` handed back carries text, not markup, so everything
    downstream -- `classify_outcome`, `normalize`, `content_hash`, the
    extraction chain -- sees exactly the shape the browser path hands it. That
    is the point: adding a fetch method must not add a branch to the scanner.
    """
    result = await impersonated_get(url, **kwargs)
    if result.text is None:
        return result

    text, found, kept = campaign_text(result.text)
    logger.info(
        "tk_campaign_page_parsed",
        url=url,
        http_status=result.http_status,
        blocks_found=found,
        blocks_kept=kept,
    )
    return FetchResult(
        text=text,
        http_status=result.http_status,
        error=result.error,
        timed_out=result.timed_out,
    )
