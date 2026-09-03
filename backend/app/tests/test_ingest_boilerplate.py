"""What a feed item carries besides the article, and what we do about it."""
import pytest

from app.ingest.boilerplate import strip_boilerplate_html, strip_boilerplate_text
from app.ingest.rss import _strip_html

# The real shape, trimmed: AeroTime wraps its related-articles rail in an
# <aside> and closes every item with the WordPress feed footer. Kept as HTML
# rather than as the flattened string because the structure IS the evidence --
# that is the whole argument of app/ingest/boilerplate.py.
AEROTIME_ITEM = """
<p>Airbus A330neo deliveries have been hampered after concerns surfaced around
the horizontal stabilizer.</p>
<figure><img src="a.jpg"/><figcaption>A Royal Jordanian Airbus A320neo.
(Credit: Steve Knight / Wikimedia Commons)</figcaption></figure>
<p>Total deliveries currently stand at 418 against 373 a year earlier.</p>
<aside class="wp-block-group related-posts">
  <article class="cs-entry">
    <span class="related-article-header">RELATED</span>
    <h2><a href="/x">Embraer delivers 2000th E-Jet, milestone reached 22 years
    after service entry</a></h2>
  </article>
</aside>
The post <a href="/y">Airbus A330neo tail section checks stump summer
deliveries: Bloomberg</a> appeared first on <a href="/z">AeroTime</a>.
"""


def test_the_rail_the_credit_and_the_footer_all_go_and_the_article_stays():
    cleaned = _strip_html(AEROTIME_ITEM)

    assert "horizontal stabilizer" in cleaned
    assert "418 against 373" in cleaned
    # The rail: another story's headline, read as this story's words.
    assert "Embraer" not in cleaned
    assert "RELATED" not in cleaned
    # The photo credit: a stock image of another carrier's aircraft is the
    # most reliable way to attach an airline the article never mentions.
    assert "Royal Jordanian" not in cleaned
    assert "Wikimedia" not in cleaned
    # The feed footer.
    assert "appeared first on" not in cleaned


def test_a_mid_body_rail_goes_too_because_the_structure_is_still_there():
    """The case the text-level cleaner deliberately refuses. WordPress splices
    rails BETWEEN paragraphs, and at ingest that is not a problem at all -- the
    <aside> is unambiguous wherever it sits."""
    html = (
        "<p>First paragraph of the report.</p>"
        '<aside class="related"><span>RELATED</span><h2>Some other story</h2></aside>'
        "<p>Second paragraph, which is reporting and must survive.</p>"
    )
    cleaned = _strip_html(html)
    assert "First paragraph" in cleaned
    assert "Second paragraph, which is reporting and must survive." in cleaned
    assert "Some other story" not in cleaned


def test_html_stripping_leaves_a_feed_with_no_furniture_untouched():
    """Most feeds carry none of this. Measured over 14 live feeds: Simple
    Flying, AirlineGeeks, ACI, FlightGlobal, PaxEx, AirlineHaber and Anadolu
    changed by 0%."""
    html = "<p>Airline reports record quarterly profit.</p><p>Revenue grew 12%.</p>"
    assert _strip_html(html) == "Airline reports record quarterly profit. Revenue grew 12%."


def test_the_stripper_never_returns_an_empty_article():
    """An item that is nothing but furniture is the gate's problem, not this
    function's -- blanking it here would hide it from the gate instead."""
    assert strip_boilerplate_text("The post X appeared first on Y.").strip()
    assert strip_boilerplate_html("") == ""
    assert strip_boilerplate_html("no markup at all") == "no markup at all"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        pytest.param(
            "The airline confirmed the order. The post FLY91 places $1 billion "
            "order appeared first on AeroTime .",
            "The airline confirmed the order.",
            id="footer_only",
        ),
        pytest.param(
            "Deliveries stand at 418. RELATED Embraer delivers 2000th E-Jet "
            "The post Airbus A330neo checks appeared first on AeroTime .",
            # The rail STAYS. See the next test for why.
            "Deliveries stand at 418. RELATED Embraer delivers 2000th E-Jet",
            id="footer_goes_rail_stays",
        ),
        pytest.param(
            "A sentence about the post office that mentions nothing else.",
            "A sentence about the post office that mentions nothing else.",
            id="the_words_the_post_alone_are_not_a_footer",
        ),
    ],
)
def test_the_archive_cleaner_removes_the_footer_and_a_trailing_rail(stored, expected):
    assert strip_boilerplate_text(stored) == expected


def test_the_archive_cleaner_refuses_a_rail_it_cannot_bound():
    """The deliberate limit, stated as a test so nobody "improves" it later.

    A rail is a headline: no terminal punctuation, no fixed length. Every
    text-level rule that catches one at the end of an article also eats a
    paragraph from the middle of another -- this stored body is the shape that
    breaks all of them, and it must come back untouched. The row is cleaned
    properly when the item is ingested again, where the <aside> still exists.
    """
    stored = (
        "First paragraph. RELATED Some other story Second paragraph, which is "
        "reporting and must survive, runs on for a while after the rail."
    )
    assert strip_boilerplate_text(stored) == stored
