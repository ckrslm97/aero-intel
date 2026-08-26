"""The contract every topic agent implements.

"Agent" here means a **topic pipeline**, not a model that browses the web at
runtime. Each agent owns a list of sources, a gate that decides what is worth
spending a classification call on, validation rules for its own domain, and the
fields a record must have before it can be published. New sources are found by
a periodic discovery pass and promoted by a person in a pull request.

That choice was made deliberately over runtime search agents. A model that goes
looking for sources on every run produces a different answer every run, and
"why is this in the paper" stops being answerable. Here the answer is always a
line in a file, with a diff and a reviewer attached.

Composition, not inheritance: an agent is anything satisfying `TopicAgent`.
The shared machinery -- fetching, language gating, clustering, scoring,
persistence -- lives in the runner and is the same for every topic. What
differs between topics is exactly the four things on this protocol, and nothing
else should end up here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.pipeline.confidence import SOURCE_TIER_SCORES

#: Source reliability, as the owner's priority ladder: official airline and
#: airport announcements first, then governments and regulators, then IATA and
#: friends, then the wires, then the trade press, with aggregator queries last.
#: Feeds straight into pipeline/confidence.py.
SourceTier = str
VALID_TIERS: frozenset[str] = frozenset(SOURCE_TIER_SCORES)


@dataclass(frozen=True)
class SourceSpec:
    """One feed, and everything the pipeline needs to know about it up front."""

    name: str
    url: str
    tier: SourceTier
    #: ISO 639-1. Declared rather than detected because the feed list is
    #: curated and finite -- see app/pipeline/language.py for why a human's
    #: claim about a feed beats a detector working on a six-word headline.
    #: None means "mixed or unknown, detect it".
    language: str | None = None
    source_type: str = "rss"
    #: Free-text note for the next person: why this source is here, or what is
    #: odd about it (an encoding quirk, a mirror domain, an item cap).
    note: str = ""

    def __post_init__(self) -> None:
        if self.tier not in VALID_TIERS:
            raise ValueError(
                f"{self.name}: unknown source tier {self.tier!r}; "
                f"expected one of {sorted(VALID_TIERS)}"
            )
        if not self.url.startswith("https://"):
            raise ValueError(f"{self.name}: source URL must be https")


@dataclass(frozen=True)
class GateResult:
    """Whether an item is worth a classification call, and why not if not.

    Every rejection carries a machine-readable reason. The old gate simply
    returned a number, so "what is the gate actually filtering out" could not
    be answered -- and a rule that was too strict looked exactly like a quiet
    week.
    """

    passed: bool
    reason: str | None = None
    score: int = 0
    #: Anything the gate learned that the classifier or the confidence pass can
    #: reuse, so the work is not repeated downstream.
    signals: dict = field(default_factory=dict)

    @classmethod
    def accept(cls, score: int = 0, **signals) -> GateResult:
        return cls(True, score=score, signals=signals)

    @classmethod
    def reject(cls, reason: str, score: int = 0, **signals) -> GateResult:
        return cls(False, reason=reason, score=score, signals=signals)


@runtime_checkable
class TopicAgent(Protocol):
    """A topic pipeline.

    Implementations are plain objects -- see app/agents/ for the real ones.
    """

    #: Stable slug, used in logs, metrics and the discovery report.
    topic: str

    #: The feeds this agent reads. Membership is owned by the file, so removing
    #: a source here deactivates it in the database on the next run (see
    #: SourceRepository.ensure_seeded).
    sources: list[SourceSpec]

    #: Fields a record must carry before it may be published. Drives the
    #: completeness component of the confidence score, which caps an incomplete
    #: record below the high band however good its source is.
    required_fields: tuple[str, ...]

    def gate(self, title: str, content: str, *, language: str) -> GateResult:
        """Decide whether this item is worth a classification call.

        Runs before any model call, on every fetched item, and must stay cheap:
        no network, no LLM. Bilingual by construction -- the previous gate's
        keyword tables were English-only, which is why a Pegasus fare campaign
        written in Turkish scored zero and was filed as general news.
        """
        ...

    def classify_prompt_fragment(self) -> str:
        """Topic-specific instructions merged into the single consolidated call.

        One call per item answers category, risk, entities, relevance and
        translation together; this is the part of the prompt that differs by
        topic. Returning "" is fine for topics that need nothing special.
        """
        ...

    def validate(self, record: dict) -> "Outcome":  # noqa: F821
        """Domain rules, applied after classification and before publication.

        Returns an Outcome (app/pipeline/outcomes.py), so an agent can say
        "this is not a campaign" as a first-class answer rather than by
        returning nothing and letting a weaker rule take over. That distinction
        is the whole point of the type.
        """
        ...
