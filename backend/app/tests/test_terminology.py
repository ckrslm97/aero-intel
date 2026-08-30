"""One aviation vocabulary, reaching both prompts.

The list used to be written twice -- a short one inside llm/prompts.py's
translate prompts (the pair that actually runs today) and a longer one inside
llm/classify_prompt.py rule 3 -- and neither carried the revenue-management
half. These tests are about the wiring, not the wording: a term added to
app/llm/terminology.py has to show up in both prompts, or the duplication is
back with extra steps.
"""
from app.llm.classify_prompt import build_prompt
from app.llm.prompts import translate_pair_prompt, translate_prompt, why_important_prompt
from app.llm.terminology import (
    AVIATION_TERMS_KEEP,
    terminology_clause_en,
    terminology_clause_tr,
)

# The terms whose absence was measured on the live feed: "yield" came back as
# "verim", "load factor" as "yük faktörü", and RASK/NDC vanished into paraphrase.
REVENUE_TERMS_THAT_WERE_MISSING = ("yield", "load factor", "RASK", "CASK", "NDC", "no-show")


def test_the_revenue_management_vocabulary_is_in_the_list():
    for term in REVENUE_TERMS_THAT_WERE_MISSING:
        assert term in AVIATION_TERMS_KEEP


def test_both_translate_prompts_carry_every_term():
    """The v1 prompts -- the ones production actually calls."""
    single = translate_prompt("Fares rose", "tr")
    paired = translate_pair_prompt("Fares rose", "Yield improved", "tr")
    for term in AVIATION_TERMS_KEEP:
        assert term in single, f"{term!r} missing from translate_prompt"
        assert term in paired, f"{term!r} missing from translate_pair_prompt"


def test_the_consolidated_classify_prompt_carries_every_term():
    """The v2 prompt (still behind CAMPAIGN_V2_ENABLED) builds rule 3 from the
    same list, so turning the flag on cannot ship the shorter vocabulary."""
    prompt = build_prompt("Başlık", "Metin")
    assert terminology_clause_tr() in prompt
    for term in AVIATION_TERMS_KEEP:
        assert term in prompt, f"{term!r} missing from the consolidated prompt"


def test_the_two_clauses_speak_the_language_of_their_prompt():
    """Not cosmetic: an English rule dropped into the Turkish prompt measurably
    lowered compliance with the Turkish rules around it, and vice versa."""
    assert "Business Class" in terminology_clause_en()
    assert "translating them literally" in terminology_clause_en()
    assert "ÇEVİRME" in terminology_clause_tr()


def test_why_important_prompt_refuses_to_speculate():
    """The assessment renders as a quote in the drawer, so an unhedged forecast
    is indistinguishable on screen from something the article said."""
    prompt = why_important_prompt("Emirates raises fares", "Yield rose.", "revenue_management")
    assert "SADECE haberin kendisinde yazanlara dayan" in prompt
    assert "Tahmin" in prompt
    # Two sentences, not an essay: this is a pull quote in a 512px panel.
    assert "en fazla iki cümleyle" in prompt
    # An article that means nothing to the desk must be allowed to produce
    # nothing at all rather than a padded sentence.
    assert "boş cevap ver" in prompt
