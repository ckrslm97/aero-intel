"""Removing the parts of a feed item that are not the article.

A feed's `content:encoded` is the rendered post, not the reporter's prose. It
carries the site's furniture with it -- a related-articles rail, the photo
credit, the WordPress "The post ... appeared first on ..." footer -- and
`get_text()` flattens all of it into one string with no seam. Everything
downstream then reads it as the article's own words:

    "RELATED Embraer delivers 2000th E-Jet, milestone reached 22 years after
     service entry The post Airbus A330neo tail section checks stump summer
     deliveries: Bloomberg appeared first on AeroTime ."

Measured on one AeroTime pull (100 items): 100 carried the footer and 40
carried at least one RELATED rail. That text is why a risk classifier can
borrow a hazard word from one teaser and a context word from another, why a
photo credit ("A Royal Jordanian Airbus A320neo") files an airline the article
never mentions, and why place resolution sees countries from four other
stories.

Two functions, because there are two moments:

`strip_boilerplate_html` runs at ingest, while the STRUCTURE is still there --
an <aside> is unambiguous in a way that no amount of guessing at the flattened
string can be. It is the real fix.

`strip_boilerplate_text` runs over already-stored prose, where the structure is
gone. It removes the footer and NOTHING else, because the footer is the only
part of this that is a fixed sentence. A rail is a headline: no terminal
punctuation, no fixed length, and after flattening there is no boundary
between it and the paragraph that follows. Every rule that would catch a rail
at the end of one article also eats reporting from the middle of another
(measured while writing this: up to 65% of a body), so old rows keep their
rails until the item is ingested again. Leaving a foreign headline in the
archive is a smaller error than deleting a paragraph of the story.
"""
import re

from bs4 import BeautifulSoup

#: Elements that are never the article. `figcaption` is here for the photo
#: credit: a stock image of another carrier's aircraft is the single most
#: reliable way to attach a wrong airline to a story.
_NON_PROSE_TAGS: tuple[str, ...] = (
    "script", "style", "noscript", "iframe", "form", "button", "aside", "nav",
    "footer", "header", "figcaption",
)

#: Substrings of `class`/`id` that name furniture rather than prose. Matched
#: case-insensitively against the whole attribute value, so "cs-entry__related"
#: and "related-article-header" both go.
_FURNITURE_HINTS: tuple[str, ...] = (
    "related", "share", "sharing", "social", "newsletter", "subscribe",
    "advert", "adsense", "promo", "sponsor", "comment", "breadcrumb",
    "author-box", "more-stories", "read-also", "read-more", "recirc",
    "latest-posts", "trending", "popular-posts", "widget",
)

#: The WordPress feed footer, as it reads once the anchors are flattened:
#: "The post <headline> appeared first on <site> ." Bounded in the middle so a
#: sentence that merely starts with "The post" cannot swallow the article.
_WP_FOOTER_RE = re.compile(
    r"\s*The post\s.{0,300}?\sappeared first on\s.{0,120}?\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)

def strip_boilerplate_html(raw_html: str) -> str:
    """Drop non-prose elements, returning HTML for the caller to flatten."""
    if not raw_html or "<" not in raw_html:
        return raw_html
    soup = BeautifulSoup(raw_html, "lxml")
    # Collected before anything is removed: decompose() detaches the subtree,
    # so a tag inspected after its parent went away has no attributes left to
    # read (bs4 raises on `.get`). Two passes, one mutation point.
    doomed = list(soup.find_all(_NON_PROSE_TAGS))
    for tag in soup.find_all(True):
        haystack = " ".join(
            [*(tag.get("class") or []), tag.get("id") or ""]
        ).lower()
        if haystack and any(hint in haystack for hint in _FURNITURE_HINTS):
            doomed.append(tag)
    for tag in doomed:
        if not tag.decomposed:
            tag.decompose()
    body = soup.body
    return body.decode_contents() if body is not None else str(soup)


def strip_boilerplate_text(text: str) -> str:
    """Remove the feed footer from already-stored prose. Nothing else."""
    if not text:
        return text
    cleaned = _WP_FOOTER_RE.sub("", text).rstrip()
    # Never hand back an empty article. An item that is nothing but furniture
    # is the gate's problem, and blanking it here would hide it from the gate
    # rather than answer it.
    return cleaned if cleaned else text
