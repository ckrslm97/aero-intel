"""Three-state classifier results.

The bug this exists to make impossible, from app/pipeline/enrich.py as it was:

    result = classify_risk(...)              # LLM
    if not result or not result.get("risk_type"):
        result = classify_risk_heuristic(...) # keyword fallback

A model correctly answering "this is not a risk" returns a null risk_type. So
does a model that timed out, returned malformed JSON, or was never called. The
three cases were indistinguishable, and all three fell through to the keyword
heuristic -- which is how a film review about the bombing of Pan Am 103 became
a high-severity attack in the United Kingdom. The model could reclassify, but
it could never *veto*.

An Outcome makes the distinction explicit and unavoidable at the type level:

    CLASSIFIED      the classifier produced an answer -> candidate for publication
    NOT_APPLICABLE  the classifier affirmatively said no -> recorded, never re-asked
    FAILED          the call did not complete -> retried later, never published

The rule that follows: a FAILED outcome must never fall back to a weaker
classifier. "No answer" means "do not show it", which is the product's own rule
about not putting unverified content in front of the reader.

NOT_APPLICABLE is persisted rather than left null so the next run does not spend
another call re-asking a question that was already answered, and so that
"assessed, and it is not a risk" is queryable and distinct from "never looked
at".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class OutcomeState(str, Enum):
    CLASSIFIED = "classified"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


@dataclass(frozen=True)
class Outcome(Generic[T]):
    """A classifier's answer, including the answer "no" and the non-answer."""

    state: OutcomeState
    payload: T | None = None
    #: Why, in machine-readable form. For NOT_APPLICABLE this is the model's own
    #: reason ("entertainment_coverage", "historical_commemoration"); for FAILED
    #: it is what went wrong ("json_parse_error", "off_taxonomy_slug",
    #: "http_timeout"). Both end up in the audit trail.
    reason: str | None = None
    #: The classifier's self-reported confidence in [0, 1], where it offers one.
    #: Feeds pipeline/confidence.py. Always None for FAILED.
    certainty: float | None = None
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state is OutcomeState.CLASSIFIED and self.payload is None:
            raise ValueError("CLASSIFIED outcome requires a payload")
        if self.state is not OutcomeState.CLASSIFIED and self.payload is not None:
            raise ValueError(f"{self.state.value} outcome must not carry a payload")
        if self.state is OutcomeState.FAILED and self.certainty is not None:
            raise ValueError("FAILED outcome cannot report certainty")
        if self.certainty is not None and not 0.0 <= self.certainty <= 1.0:
            raise ValueError(f"certainty out of range: {self.certainty}")

    # --- constructors, so call sites read as the thing they mean -------------

    @classmethod
    def classified(cls, payload: T, *, certainty: float | None = None, **details) -> Outcome[T]:
        return cls(
            OutcomeState.CLASSIFIED, payload=payload, certainty=certainty, details=details
        )

    @classmethod
    def not_applicable(cls, reason: str, *, certainty: float | None = None) -> Outcome[T]:
        """The classifier looked and said no. This is a real answer."""
        return cls(OutcomeState.NOT_APPLICABLE, reason=reason, certainty=certainty)

    @classmethod
    def failed(cls, reason: str) -> Outcome[T]:
        """The classifier did not answer. Never publish on this."""
        return cls(OutcomeState.FAILED, reason=reason)

    # --- predicates ----------------------------------------------------------

    @property
    def is_classified(self) -> bool:
        return self.state is OutcomeState.CLASSIFIED

    @property
    def is_failure(self) -> bool:
        return self.state is OutcomeState.FAILED

    @property
    def was_assessed(self) -> bool:
        """True when the classifier reached a conclusion, "no" included.

        The condition for writing an `assessed_at` timestamp: a failure is not
        an assessment, so it stays pending and gets retried.
        """
        return self.state is not OutcomeState.FAILED

    @property
    def is_publishable(self) -> bool:
        """Only a classification can reach the reader.

        Deliberately not `not is_failure`: NOT_APPLICABLE is a successful
        assessment whose conclusion is that there is nothing to show.
        """
        return self.state is OutcomeState.CLASSIFIED
