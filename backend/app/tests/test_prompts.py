"""The live providers' prompts, where they carry taxonomy decisions.

Two things are worth pinning. The subcategory options are read out of
SUBCATEGORY_KEYWORDS rather than retyped, so adding a slug to app/taxonomy.py is
the whole change -- and the same dict is what openai_compat.subcategorize()
validates the answer against, so a prompt that offered a different set would
have the model answering questions its reply is then rejected for.

And the fleet/finance -> revenue_management rule has to reach the model at all.
It is the one editorial rule in this file that a model would not infer: left to
itself it reads "50 aircraft" as capacity and empties Filo into Gelir Yönetimi,
which is exactly what the negative examples are there to stop.
"""
from app.llm.prompts import categorize_prompt, subcategorize_prompt
from app.taxonomy import CATEGORY_SLUGS, SUBCATEGORY_KEYWORDS


def test_categorize_prompt_offers_every_category():
    prompt = categorize_prompt("t", "c")
    for slug in CATEGORY_SLUGS:
        assert slug in prompt, slug


def test_categorize_prompt_carries_the_rm_shift_rule_with_both_directions():
    prompt = categorize_prompt("t", "c")
    assert "ÖZEL KURAL" in prompt
    # The rule is worthless without its boundary: a positive case that moves and
    # a negative one that must not.
    assert "EVET:" in prompt
    assert "HAYIR:" in prompt
    assert "kapasite" in prompt.lower()
    assert "sipariş" in prompt.lower(), "the plain-order counter-example is the guardrail"


def test_subcategorize_prompt_lists_the_slugs_the_reply_is_validated_against():
    """Includes the slugs this round added -- demand, capacity, forecasting and
    the nine airport beats -- without any of them being typed into prompts.py."""
    for category, subs in SUBCATEGORY_KEYWORDS.items():
        prompt = subcategorize_prompt("t", "c", category)
        for slug in subs:
            assert slug in prompt, f"{category}/{slug} missing from its prompt"


def test_subcategorize_prompt_offers_none_for_a_flat_category():
    assert "none" in subcategorize_prompt("t", "c", "safety")
