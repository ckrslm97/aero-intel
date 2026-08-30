"""The aviation vocabulary a translation must leave alone -- one list, two prompts.

"Business class" is Business class in Turkish too; an earlier prompt rendered
it "iş sınıfı". The fix was an exemplar list inside the prompt, and it was
written twice: llm/prompts.py (the v1 translate prompts, which are what
actually runs today) got a short one, llm/classify_prompt.py rule 3 (the v2
consolidated prompt, still behind CAMPAIGN_V2_ENABLED) got a longer one, and
neither carried the revenue-management vocabulary this desk reads all day.
Measured on the live feed, that is the half that hurts: "yield" came back as
"verim", "load factor" as "yük faktörü", "no-show" as "gelmeyen yolcu", and
RASK/CASK/NDC simply disappeared into paraphrase.

So the list lives here once and both prompts build their clause from it. A term
added for one prompt is a term added for both, and neither file can quietly
drift into having the shorter half of the vocabulary again.

Scope note: this is a KEEP-AS-WRITTEN list, not a glossary. It never says what
a term means in Turkish, because the whole point is that it stays in English --
adding a translation column would be inviting exactly the substitution the list
exists to prevent.
"""
from __future__ import annotations

#: Cabin and product names. A Turkish aviation reader says "Business class",
#: and every airline's own Turkish site does too.
CABIN_TERMS: tuple[str, ...] = (
    "Business Class",
    "Economy",
    "Premium Economy",
    "First Class",
)

#: Revenue management proper -- the beat this paper leads with, and the half
#: both prompts were missing. Left in English because that is how they appear
#: in a Turkish RM desk's own reporting; there is no accepted Turkish form for
#: RASK or NDC, and inventing one makes the sentence harder to read, not easier.
REVENUE_MANAGEMENT_TERMS: tuple[str, ...] = (
    "yield",
    "load factor",
    "RASK",
    "CASK",
    "ASK",
    "RPK",
    "PRASK",
    "unit revenue",
    "dynamic pricing",
    "fare family",
    "ancillary revenue",
    "overbooking",
    "no-show",
    "upgrade",
    "NDC",
    "GDS",
)

#: Network, scheduling and commercial agreements.
NETWORK_TERMS: tuple[str, ...] = (
    "codeshare",
    "interline",
    "slot",
    "hub",
    "layover",
    "stopover",
    "block hour",
    "ferry flight",
)

#: Fleet and operations.
FLEET_TERMS: tuple[str, ...] = (
    "wet lease",
    "dry lease",
    "sale and leaseback",
    "MRO",
    "turnaround",
)

#: The whole vocabulary, in reading order rather than alphabetical: a prompt is
#: read by a model left to right, and grouping related terms keeps the clause
#: from looking like a random word list.
AVIATION_TERMS_KEEP: tuple[str, ...] = (
    *CABIN_TERMS,
    *REVENUE_MANAGEMENT_TERMS,
    *NETWORK_TERMS,
    *FLEET_TERMS,
)


def _joined(terms: tuple[str, ...]) -> str:
    return ", ".join(terms)


def terminology_clause_en() -> str:
    """The English "do not translate these" clause, for llm/prompts.py.

    One sentence, because it is embedded in a longer instruction that already
    names airline/airport names, IATA codes and type designators -- this adds
    the industry vocabulary those three categories do not cover.
    """
    return (
        "standard aviation and revenue-management industry terms "
        f"(e.g. {_joined(AVIATION_TERMS_KEEP)}) in their original English or "
        "internationally recognized form rather than translating them literally"
    )


def terminology_clause_tr() -> str:
    """The Turkish clause, for llm/classify_prompt.py rule 3.

    Turkish because the consolidated prompt is written in Turkish end to end;
    an English rule inside it measurably lowered compliance with the rules
    around it.
    """
    return (
        "Havacılık ve gelir yönetimi terimlerini ÇEVİRME; olduğu gibi bırak: "
        f"{_joined(AVIATION_TERMS_KEEP)}."
    )
