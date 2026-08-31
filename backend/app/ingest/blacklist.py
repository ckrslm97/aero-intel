"""Domain blacklist -- publishers whose content must never enter the archive.

Reddit is the whole list today, on the owner's instruction ("Reddit tamamen
kaldırılmalı"). The two Reddit *sources* were already removed from
sources_seed.py in an earlier round, but that only closed the front door:
Reddit threads kept arriving as items inside the Google News radars, because a
Google News query returns whatever publisher ranked for it and reddit.com ranks
for almost every consumer-travel phrase. A community thread filed as a fare
campaign is exactly the failure the source removal was meant to end, so the ban
has to live at the item level, not the source level.

Deliberately a plain module with no third-party imports: the ingest adapter
(which pulls feedparser/lxml/BeautifulSoup) and the maintenance purge (which
pulls SQLAlchemy) both need this matcher, and neither should drag the other's
dependencies in behind it.

WHAT IS AND IS NOT DETECTABLE
-----------------------------
A direct feed gives us the publisher's own URL, so `link` is enough.

Google News does not. Its `<link>` is a wrapper of the form

    https://news.google.com/rss/articles/CBMifkFVX3lxTE85Q0JZcDFvMXdV...?oc=5

and the token after `CBMi` is NOT the target URL in any encoding -- decoded
from base64 it is a protobuf holding an opaque `AU_yqL...` identifier that only
Google's own redirect can resolve. Verified by hand at build time; do not add a
"just base64-decode it" shortcut, it decodes to nothing useful.

What Google News *does* give us is the `<source url="https://www.reddit.com">`
element on every item, which names the publisher exactly. That is what
`RssSourceAdapter` passes as `wrapped_url`, and it is the honest limit of this
check: a wrapped item is judged by the publisher Google declares. If Google ever
stops emitting `<source>`, a Reddit item behind a wrapper becomes undetectable
at ingest time and would need the redirect followed (an extra HTTP request per
item) -- the purge below is the backstop for that case.
"""
import re

#: Registrable domains, not hostnames. A host matches if it *is* one of these
#: or is a subdomain of one, so old./np./www./i./v. are all covered without
#: being listed. Substring matching is deliberately NOT used: "reddit.com" is a
#: substring of the perfectly innocent "notreddit.com" and of a path like
#: "example.com/r/reddit.com", and both would be banned by accident.
BLACKLISTED_DOMAINS: frozenset[str] = frozenset(
    {
        "reddit.com",
        "redd.it",  # link shortener + i.redd.it / v.redd.it media hosts
        "reddit.media",
        "redditstatic.com",
        "redditmedia.com",
    }
)

#: Article.status for a row retired by the purge. Sits alongside the pipeline's
#: other rejected_* states (rejected_language, rejected_gate) rather than
#: inventing a new mechanism: a blacklisted article is a rejection with a
#: reason, and rejections are kept, never deleted, so the count stays auditable.
BLACKLIST_STATUS = "rejected_blacklist"


#: A URL scheme, per RFC 3986: letter, then letters/digits/+/-/. up to the ":".
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def _host(url: str | None) -> str | None:
    """Lowercased hostname, or None if `url` has no parseable web host.

    Hand-rolled rather than urllib.parse.urlsplit because a feed link is
    untrusted input that is frequently not a URL at all (a bare title, an empty
    string, a mailto:), and urlsplit's answer for those is an empty netloc that
    reads as "no host" only if the caller remembers to check. Splitting on the
    delimiters here keeps the whole rule visible in one place.

    Schemes other than http(s) return None even when they contain a
    blacklisted-looking string: "mailto:someone@reddit.com" has an address, not
    a publisher, and can never be an ingested article.
    """
    if not url:
        return None
    remainder = url.strip()
    scheme_match = _SCHEME.match(remainder)
    if scheme_match:
        if scheme_match.group(1).lower() not in {"http", "https"}:
            return None
        remainder = remainder[scheme_match.end():].lstrip("/")
    # Cut the authority off the path/query/fragment first, then drop any
    # userinfo inside it. Doing it in this order matters: an "@" in a query
    # string ("?to=x@reddit.com") is not userinfo and must not become the host.
    authority = remainder.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    host = authority.split(":", 1)[0].strip().lower().rstrip(".")
    return host or None


def blacklisted_domain(url: str | None) -> str | None:
    """The blacklisted registrable domain `url` belongs to, or None.

    Returns the domain rather than a bool so callers can log and store *which*
    rule fired -- "blacklist:reddit.com" in rejection_reason is answerable six
    months from now; a bare True is not.
    """
    host = _host(url)
    if host is None:
        return None
    for domain in BLACKLISTED_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None


def is_blacklisted(*urls: str | None) -> bool:
    """True if any of the given URLs resolves to a blacklisted domain.

    Variadic because an aggregator item has two candidate URLs -- the wrapper
    Google published and the publisher it names -- and either one being Reddit
    is enough to drop the item.
    """
    return any(blacklisted_domain(url) is not None for url in urls)
