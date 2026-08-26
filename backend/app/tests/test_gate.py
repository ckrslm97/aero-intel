"""The pre-LLM gate, against the articles that got through it.

Every string marked "published" below is a real row the pipeline put in front
of a reader. They are the specification.
"""
import pytest

from app.agents.gate import DEFAULT_THRESHOLD, evaluate

# --- what must get through ---------------------------------------------------


@pytest.mark.parametrize(
    "title,why",
    [
        (
            "Pegasus'ta 6 hatta yüzde 50'ye varan indirim kampanyası başladı",
            "a direct competitor fare campaign -- the thing this product exists "
            "to catch. Filed as `general` before, because 'kampanya' and "
            "'indirim' were subcategory keywords and subcategorisation only "
            "runs after a category has already won.",
        ),
        (
            "Airbus'ta Süresiz Grev Kararı!",
            "indefinite strike at the largest aircraft manufacturer, scored 3 "
            "against a threshold of 6 for being tersely worded in Turkish",
        ),
        ("THY Uçağında Yolcu Hayatını Kaybetti", "home carrier, safety"),
        ("Air passenger demand falls in June, IATA says", "regulator, demand"),
        (
            "Turkish Airlines Targets Lima As Latin America Expansion Continues",
            "network news that the old gate scored below the line for brevity",
        ),
        (
            "Türk Hava Yolları kış tarifesinde Avrupa'ya ek sefer koyuyor",
            "Turkish capacity news, entirely invisible to an English-only gate",
        ),
    ],
)
def test_aviation_business_news_passes(title, why):
    result = evaluate(title, "")
    assert result.passed, f"{title!r} should pass: {why}"
    assert result.score >= DEFAULT_THRESHOLD


# --- what must not ------------------------------------------------------------


@pytest.mark.parametrize(
    "title,reason",
    [
        # published: 6 credit-card posts in a 200-article sample cleared the old
        # gate on bare `bonus` / `offer`, each worth 6 points on a presence test.
        ("Is The Amex Blue Business Credit Card Worth It?", "off_domain:card"),
        (
            "Get more than $4,000 in value with the 200,000-point bonus on the "
            "Chase Sapphire Reserve",
            "off_domain:card",
        ),
        # Rejected for having no aviation vocabulary at all rather than as
        # card content -- either way it never reaches the classifier, which
        # is what matters. It was published as `regulatory` before, on the
        # bare keyword `rule`.
        ("These 6 business cards can help you stay under Chase's 5/24 rule", "no_aviation_terms"),
        # published as airline campaigns, three rows of them.
        ("Etihad Rail passenger tickets: How to book, 50% discount on fares", "off_domain:rail"),
        ("İlk Eurostar Premier Uçuşum Düzgündü, Sessizdi ve Uçmadan Daha İyi", "off_domain:rail"),
        # published, attributed to Emirates.
        ("Marriott Bonvoy: Puanlara, elit statüye ve daha fazlasına kapsamlı rehber", "off_domain:hotel"),
        ("Review: Airelles Palladio Venice, Italy (What A Gorgeous City Resort!)", "off_domain:hotel"),
        # in the feed only because the cycling team is airline-sponsored.
        (
            "Tadej Pogačar mounts imperious attack to win stage 4 of the Vuelta a España",
            "off_domain:sport",
        ),
        ("Pumpkin spice is back at Starbucks", "no_aviation_terms"),
        ("ABD'de konut fiyatlarındaki yıllık artış haziranda yüzde 1,5 oldu", "no_aviation_terms"),
    ],
)
def test_off_domain_content_is_rejected_with_a_reason(title, reason):
    result = evaluate(title, "")
    assert not result.passed, f"{title!r} should not reach the classifier"
    assert result.reason == reason


def test_a_promotional_term_alone_does_not_open_the_gate():
    """`discount`, `offer`, `sale` and `bonus` each cleared the old gate on
    their own. A discount on something that is not a flight is not a fare
    campaign."""
    result = evaluate("Huge discount on garden furniture this weekend", "")
    assert not result.passed
    assert result.reason == "no_aviation_terms"


def test_promotional_term_plus_aviation_does_open_it():
    result = evaluate("Qatar Airways offers discount on fares to Athens", "")
    assert result.passed
    assert result.signals["promo"] is True


# --- the title decides the subject -------------------------------------------


def test_a_watched_carrier_in_the_title_beats_a_neighbouring_industry():
    """The rule must not become a keyword veto: an airline's own hotel or rail
    partnership is legitimately aviation news."""
    result = evaluate("Turkish Airlines partners with Marriott on loyalty tie-up", "")
    assert result.passed

    result = evaluate("Emirates adds rail connection to Dubai airport terminal", "")
    assert result.passed


def test_a_neighbouring_industry_in_the_title_wins_when_no_carrier_is_named():
    """`Etihad Rail passenger tickets ... discount on fares` matched `passenger`
    and `fares` and out-scored the rail signal on body counts, so it published
    as an airline campaign. The headline names the subject."""
    result = evaluate("Etihad Rail passenger tickets: How to book", "")
    assert not result.passed
    assert result.reason == "off_domain:rail"


# --- mechanics ----------------------------------------------------------------


def test_turkish_diacritics_survive_matching():
    """fold_text maps ı/ğ/ş/ç/ö/ü onto ASCII before matching. Without it,
    normalize_text's character class turns "uçuş" into "u u" and every Turkish
    term in the tables becomes unmatchable."""
    assert evaluate("İstanbul Havalimanı'nda uçuş trafiği arttı", "").passed


def test_headline_only_items_are_not_gated_out_for_having_no_body():
    """The Google News radars deliver headlines with no body; 804 of 997
    waiting articles had under 120 characters of it."""
    short = evaluate("Pegasus announces new route to Tbilisi", "")
    assert short.passed


def test_rejection_always_carries_a_machine_readable_reason():
    """A gate that is too strict and a quiet news week look identical without
    one."""
    for title in ("Pumpkin spice is back at Starbucks", "Local bakery wins award"):
        result = evaluate(title, "")
        assert not result.passed
        assert result.reason, title


def test_gate_does_not_classify():
    """The gate answers "is this worth asking about", not "what is it". It
    reports signals; it does not pick a category -- that is the model's job and
    keyword categorisation is what produced a 27.5% error rate."""
    result = evaluate("Turkish Airlines reports record load factor", "")
    assert result.passed
    assert "category" not in result.signals
