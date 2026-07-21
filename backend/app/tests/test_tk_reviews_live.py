"""Offline tests for the live TK review refresh.

Nothing here touches the network: the App Store JSON, the Skytrax <article>
block and the Reddit Atom entry are verbatim captures of real responses taken
while writing app/ingest/tk_reviews_live.py, so a markup change upstream shows
up as a parser test failure rather than as a silent empty refresh.
"""
import httpx
import pytest

from app.ingest import tk_reviews_live as live
from app.ingest.tk_reviews_live import (
    SOURCE_APPSTORE,
    SOURCE_REDDIT,
    SOURCE_SKYTRAX,
    LiveReview,
    _squash,
    clip_excerpt,
    is_near_duplicate,
    is_quotable,
    parse_appstore,
    parse_reddit,
    parse_skytrax,
    refresh_tk_reviews,
    tag_themes,
)

APPSTORE_PAYLOAD = {
    "feed": {
        "entry": [
            {
                "author": {"name": {"label": "Andrea.B.."}},
                "updated": {"label": "2026-07-18T12:11:51-07:00"},
                "im:rating": {"label": "1"},
                "title": {"label": "Schedule changes"},
                "content": {
                    "label": (
                        "Changing flights by days, not merely hours, is not acceptable. "
                        "I've now incurred an extra 2 days of hotel costs."
                    ),
                    "attributes": {"type": "text"},
                },
            },
            # App-only complaint: real feed content, but not a passenger review.
            {
                "author": {"name": {"label": "gulli hanko"}},
                "updated": {"label": "2026-07-18T12:11:51-07:00"},
                "im:rating": {"label": "1"},
                "title": {"label": "Sevilsen"},
                "content": {
                    "label": (
                        "Website timed out and made me lose the lower rate. "
                        "The app charged me $75 extra within minutes."
                    ),
                },
            },
            {
                "author": {"name": {"label": "Malek Rabah"}},
                "updated": {"label": "2026-07-11T04:02:00-07:00"},
                "im:rating": {"label": "5"},
                "title": {"label": "Excellent"},
                "content": {"label": "Friendly cabin crew and the meal was great."},
            },
            # App-metadata rows carry no im:rating and must be dropped.
            {"title": {"label": "Turkish Airlines"}, "im:name": {"label": "Turkish Airlines"}},
        ]
    }
}

# Verbatim from https://www.airlinequality.com/airline-reviews/turkish-airlines/
# (the per-category star rows further down the stats table are elided; the
# parser never reads them).
SKYTRAX_HTML = """
<div class="listing">
<article itemprop="review" itemscope itemtype="http://schema.org/Review"
         class="comp comp_media-review-rated list-item media position-content review-950306">
    <meta itemprop="datePublished" content="2026-07-17">
    <div itemprop="reviewRating" itemscope itemtype="http://schema.org/Rating" class="rating-10">
        <span itemprop="ratingValue">9</span>/<span itemprop="bestRating">10</span>
    </div>
    <div class="body" id="anchor950306">
        <h2 class="text_header">&quot;Keep up the excellent work&quot;</h2>
        <h3 class="text_sub_header userStatusWrapper">
            <span itemprop="author" itemscope itemtype="http://schema.org/Person">
            <span itemprop="name">Karim Fahim Fahim</span></span> (Czech Republic)
            <time itemprop="datePublished" datetime="2026-07-17">17th July 2026</time></h3>
        <div class="tc_mobile">
        <div class="text_content " itemprop="reviewBody">&#9989;
            <strong><a href="https://www.airlinequality.com/verified-reviews/">
            <em>Trip Verified</em></a></strong> | User friendly mobile application, an easy
            website. Onboard very clean cabin, friendly cabin crew, new A321 NEO, delicious
            catering, updated infotainment system. Keep up the excellent work.</div>
        <div class="review-stats">
            <table class="review-ratings">
                <tr><td class="review-rating-header type_of_traveller ">Type Of Traveller</td>
                    <td class="review-value ">Solo Leisure</td></tr>
                <tr><td class="review-rating-header cabin_flown ">Seat Type</td>
                    <td class="review-value ">Economy Class</td></tr>
                <tr><td class="review-rating-header route ">Route</td>
                    <td class="review-value ">Prague to Cairo </td></tr>
                <tr><td class="review-rating-header date_flown ">Date Flown</td>
                    <td class="review-value ">July 2026</td></tr>
            </table>
        </div>
        </div>
    </div>
</article>
</div>
"""

REDDIT_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <author><name>/u/ok_goal9999</name></author>
  <content type="html">&lt;table&gt;&lt;tr&gt;&lt;td&gt;
    &lt;div class="md"&gt;&lt;p&gt;Flights were great, food was great!&lt;/p&gt;
    &lt;p&gt;I love the fact that they give hot towels to everyone.&lt;/p&gt;&lt;/div&gt;
    &amp;#32; submitted by &amp;#32;
    &lt;a href="https://www.reddit.com/user/ok_goal9999"&gt;/u/ok_goal9999&lt;/a&gt;
  &lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</content>
  <id>t3_1uz498b</id>
  <link href="https://www.reddit.com/r/TurkishAirlines/comments/1uz498b/first_time/" />
  <updated>2026-07-19T09:12:00+00:00</updated>
  <title>First time on Turkish Airlines</title>
</entry>
</feed>
"""


def test_appstore_parsing_converts_stars_to_ten_point_scale():
    reviews = parse_appstore(APPSTORE_PAYLOAD, "gb")

    # The rating-less app-metadata row and the app-only complaint are dropped.
    assert len(reviews) == 2
    bad, good = reviews
    assert bad.rating == 2.0  # 1 star
    assert good.rating == 10.0  # 5 stars
    assert good.rating_note == "5/5 App Store (GB)"
    assert good.author == "Malek Rabah"
    assert good.review_date.isoformat() == "2026-07-11"
    assert bad.author == "Andrea.B.."
    assert bad.url.endswith("/gb/app/turkish-airlines-book-flights/id1283414961")
    assert bad.source_name == SOURCE_APPSTORE
    assert not any("Website timed out" in r.excerpt for r in reviews)


def test_skytrax_parsing_reads_microdata_and_strips_verified_prefix():
    reviews = parse_skytrax(SKYTRAX_HTML, "https://www.airlinequality.com/x/page/2/")

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source_name == SOURCE_SKYTRAX
    assert review.rating == 9.0
    assert review.author == "Karim Fahim Fahim"
    assert review.review_date.isoformat() == "2026-07-17"
    assert review.route == "Prague to Cairo"
    assert "Trip Verified" not in review.excerpt
    assert review.excerpt.startswith("User friendly mobile application")
    # The permalink is anchored to the base listing URL, not to page/2/, so a
    # review sliding between pages keeps the same dedupe key.
    assert review.url == (
        "https://www.airlinequality.com/airline-reviews/turkish-airlines/#anchor950306"
    )


def test_reddit_parsing_quotes_post_body_not_feed_boilerplate():
    reviews = parse_reddit(REDDIT_RSS)

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source_name == SOURCE_REDDIT
    assert review.author == "u/ok_goal9999"
    assert review.rating is None
    assert "submitted by" not in review.excerpt
    assert review.excerpt.startswith("Flights were great")


def test_theme_tagging_maps_keywords_to_review_theme_slugs():
    assert tag_themes("The cabin crew were lovely and the meal was excellent") == [
        "cabin_crew",
        "food",
    ]
    assert set(tag_themes("Flight delayed, my luggage never arrived")) == {"delay", "baggage"}
    assert set(tag_themes("Tight legroom and the wifi screen was broken")) == {
        "seat_comfort",
        "entertainment",
    }
    assert set(tag_themes("Miles were useless and customer service refused a refund")) == {
        "miles_smiles",
        "refund_service",
    }
    assert tag_themes("Istanbul connection was smooth") == ["ist_transfer"]
    assert tag_themes("Overpriced for the value you get") == ["value"]
    assert tag_themes("") == []
    # "bag" must not fire on "bagel", "ist" must not fire on "exist".
    assert tag_themes("The bagel did not exist on the tray") == []


def test_app_only_complaints_are_not_passenger_reviews():
    # Real App Store text: nothing to do with flying Turkish Airlines.
    assert not is_quotable("this is the only app i have seen that i can't paste my password into")
    assert not is_quotable("Lots of bugs and stability issues on the website, please fix")
    # ...but a software gripe attached to a real flight stays.
    assert is_quotable("The app is clunky, but the cabin crew on the flight were lovely.")
    # Too short to be an opinion at all ("10", emoji-only ratings).
    assert not is_quotable("10")
    assert not is_quotable("❤️🇹🇷🇹🇷")
    # Obvious chatbot paste -- quoting it as a passenger's words would be false.
    assert not is_quotable("Okay, here's a draft in your voice. Our flight was around 11 hours.")


def test_non_english_reviews_survive_the_filters():
    """The TR and DE storefronts are a big slice of the feed, and the theme
    keywords are English-only -- the filters must not become a language test."""
    assert is_quotable("Yıllardan beri Türk Hava Yollarını kullanıyorum, hiç sorun yaşamadım.")
    assert is_quotable("Totalmente complacido con el servicio de la aerolinea en tierra y aire")
    assert _squash("Türk Hava Yolları") == "türkhavayolları"


def test_near_duplicate_survives_a_different_clip_point():
    """The curated seed and the live pass clip the same review differently and
    file it under different URLs; only the text overlap can catch that."""
    seed = _squash(
        "Our flight to Istanbul from Durban/Johannesburg was delayed by over 12 "
        "hours and we missed our connecting flight."
    )
    live_shorter = "Our flight to Istanbul from Durban/Johannesburg was delayed by over 12 hours."

    assert is_near_duplicate(live_shorter, [seed])
    assert not is_near_duplicate("Amazing food, seats and crew on the A350 to Tokyo.", [seed])


def test_long_excerpt_is_clipped_at_a_sentence_boundary():
    first = "The crew were attentive throughout the flight and never once seemed rushed."
    second = "Boarding at Istanbul was chaotic as usual with nobody respecting the queue."
    third = "I would still fly with them again because the price was unbeatable."
    long_text = " ".join([first, second, third])

    clipped = clip_excerpt(long_text)

    assert len(clipped) <= 280
    assert clipped == f"{first} {second}"  # two whole sentences, third dropped
    assert third not in clipped


def test_single_runaway_sentence_is_cut_on_a_word_boundary():
    runaway = "the crew were absolutely wonderful and " * 20  # 760 chars, no full stop

    clipped = clip_excerpt(runaway)

    assert len(clipped) <= 280
    assert clipped.endswith("…")
    assert not clipped[:-1].endswith(" ")
    assert "wonderfu…" not in clipped  # never cut mid-word


def _stub_fetcher(reviews: list[LiveReview]):
    async def fetch(_client: httpx.AsyncClient) -> list[LiveReview]:
        return list(reviews)

    return fetch


def _boom(_client: httpx.AsyncClient):
    raise httpx.ConnectTimeout("airlinequality.com did not answer")


SAMPLE = LiveReview(
    source_name=SOURCE_SKYTRAX,
    url="https://www.airlinequality.com/airline-reviews/turkish-airlines/#anchor950306",
    excerpt="Onboard very clean cabin, friendly cabin crew, delicious catering.",
    rating=9.0,
    author="Karim Fahim Fahim",
    route="Prague to Cairo",
)


async def test_fetching_the_same_review_twice_creates_one_row(db_session, monkeypatch):
    monkeypatch.setattr(live, "FETCHERS", {SOURCE_SKYTRAX: _stub_fetcher([SAMPLE])})

    first = await refresh_tk_reviews(db_session)
    second = await refresh_tk_reviews(db_session)

    assert first == {
        "fetched": 1,
        "inserted": 1,
        "sources": {SOURCE_SKYTRAX: 1},
        "errors": {},
    }
    assert second["fetched"] == 1
    assert second["inserted"] == 0  # dedupe_key already present


async def test_stored_review_is_scored_tagged_and_left_untranslated(db_session, monkeypatch):
    monkeypatch.setattr(live, "FETCHERS", {SOURCE_SKYTRAX: _stub_fetcher([SAMPLE])})
    await refresh_tk_reviews(db_session)

    from sqlalchemy import select

    from app.models.tk_review import TkReview

    row = (await db_session.execute(select(TkReview))).scalar_one()
    assert row.sentiment == "positive"  # derived from the 9/10 score
    assert set(row.themes) >= {"cabin_crew", "food"}
    assert row.excerpt_tr is None  # translation is a separate, LLM-funded pass
    assert row.rating == 9.0


async def test_one_dead_source_does_not_stop_the_others(db_session, monkeypatch):
    other = LiveReview(
        source_name=SOURCE_APPSTORE,
        url="https://apps.apple.com/us/app/turkish-airlines-book-flights/id1283414961",
        excerpt="Friendly crews and clean plane, the food was very nice.",
        rating=10.0,
        author="Real Baba Agba",
    )
    monkeypatch.setattr(
        live,
        "FETCHERS",
        {
            SOURCE_SKYTRAX: _boom,
            SOURCE_APPSTORE: _stub_fetcher([other]),
        },
    )

    result = await refresh_tk_reviews(db_session)

    assert result["inserted"] == 1
    assert result["sources"] == {SOURCE_SKYTRAX: 0, SOURCE_APPSTORE: 1}
    assert SOURCE_SKYTRAX in result["errors"]


async def test_a_curated_seed_row_is_not_duplicated_by_the_live_fetch(db_session, monkeypatch):
    """The seed stores Skytrax reviews under the bare listing URL; the live pass
    stores them under an anchored one. Different dedupe_key, same words -- the
    fingerprint guard is what keeps the BİZ page from showing both."""
    from app.models.tk_review import TkReview

    db_session.add(
        TkReview(
            source_name=SOURCE_SKYTRAX,
            url="https://www.airlinequality.com/airline-reviews/turkish-airlines/",
            dedupe_key="curated-key",
            excerpt="Onboard very clean cabin, friendly cabin crew, delicious catering.",
            excerpt_tr="Temiz kabin, güler yüzlü ekip, lezzetli ikram.",
            sentiment="positive",
            themes=["cabin_crew"],
        )
    )
    await db_session.commit()

    monkeypatch.setattr(live, "FETCHERS", {SOURCE_SKYTRAX: _stub_fetcher([SAMPLE])})
    result = await refresh_tk_reviews(db_session)

    assert result["inserted"] == 0


@pytest.mark.parametrize(
    ("rating", "expected"),
    [(10.0, "positive"), (7.0, "positive"), (6.0, "neutral"), (4.0, "negative")],
)
async def test_score_beats_the_lexicon_when_the_source_publishes_one(rating, expected):
    # "delay" is a negative lexicon word; a high score must still win.
    assert await live.sentiment_for(rating, "There was a delay but it was wonderful") == expected


async def test_scoreless_sources_fall_back_to_the_heuristic_lexicon():
    assert await live.sentiment_for(None, "Flight was cancelled after a long delay") == "negative"
