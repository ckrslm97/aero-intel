"""What language an article is in, decided before anything else runs.

There was no language detection anywhere in the pipeline. Grepping `ingest/`,
`pipeline/` and `api/v1/` for it returned only comments. The consequence,
measured over 200 production articles: 36 of them (18%) were German or Spanish,
none were translated, and all of them reached a Turkish-language UI as raw
foreign text -- headlines like `Warum Premium-Reisende ihren Aperitif in den
USA künftig früher abgeben müssen` rendered as news to a Turkish revenue desk.

Two mechanisms, in this order:

1. **The source declares its language.** The feed list is curated and finite,
   so for almost every article this is already known and needs no inference.
   aeroTELEGRAPH publishes German; a Google News query with `hl=tr&gl=TR`
   returns Turkish. Declaration is auditable in a way detection is not.

2. **Detection as the safety net**, for feeds that genuinely mix languages
   (Aviation24.be is a Belgian outlet publishing mostly English with occasional
   Dutch and French) and for sources whose declaration is missing.

Detection wins over declaration only when it is *confident*, because a
declaration is a human's considered claim about a feed and a detector working
on a six-word headline is not. Below that bar the declaration stands, and when
there is no declaration either, the article is rejected rather than guessed at
-- the pipeline's standing rule is that not knowing means not publishing.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

#: The only two languages this product publishes in. Everything else is
#: rejected at ingest: the UI is Turkish, translation is budgeted for the
#: languages the desk actually reads, and an untranslated German headline in a
#: Turkish paper is worse than a gap.
SUPPORTED: frozenset[str] = frozenset({"en", "tr"})

#: Detection has to be at least this sure before it overrules the source's own
#: declaration. Calibrated on real headlines: genuine matches land at 0.95+,
#: while short brand-only fragments ("Pegasus BolBol") land near 0.67 and are
#: exactly the case where the feed's declaration is the better answer.
OVERRIDE_CONFIDENCE = 0.90

#: Below this, detection is treated as having no opinion at all.
MIN_CONFIDENCE = 0.65

#: Detection needs something to work with. Headline-only items from the Google
#: News radars are often under 40 characters, which is where a detector starts
#: guessing from brand names -- so short text leans on the declaration.
MIN_CHARS = 24


@dataclass(frozen=True)
class LanguageVerdict:
    language: str | None
    #: "declared" | "detected" | "detected_over_declared" | "unknown"
    basis: str
    confidence: float | None = None

    @property
    def is_supported(self) -> bool:
        return self.language in SUPPORTED

    @property
    def rejection_reason(self) -> str | None:
        """The machine-readable reason stored on the rejected article."""
        if self.is_supported:
            return None
        if self.language is None:
            return "language:unknown"
        return f"language:{self.language}"


@lru_cache(maxsize=1)
def _identifier():
    """Loaded once. The model is ~700KB and reading it per article would cost
    more than the classification."""
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    # norm_probs gives a 0-1 probability instead of a raw log-likelihood, which
    # is what makes the thresholds above expressible as numbers a reader can
    # reason about.
    return LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)


def detect(text: str) -> tuple[str | None, float]:
    """Raw detection. Returns (language, probability), or (None, 0.0) when the
    text is too short to say anything about."""
    sample = (text or "").strip()
    if len(sample) < MIN_CHARS:
        return None, 0.0
    language, probability = _identifier().classify(sample)
    if probability < MIN_CONFIDENCE:
        return None, float(probability)
    return language, float(probability)


def resolve(
    title: str, content: str = "", *, declared: str | None = None
) -> LanguageVerdict:
    """Decide an article's language from its text and its source's declaration.

    The body is included when there is one: detection on a full paragraph is
    far more reliable than on a headline, and the Google News radars deliver
    headlines only.
    """
    # A bounded sample: the first few hundred characters settle it, and feeding
    # a 3,000-word body through the classifier buys nothing.
    sample = f"{title or ''} {(content or '')[:600]}".strip()
    detected, confidence = detect(sample)

    if declared is None:
        if detected is None:
            return LanguageVerdict(None, "unknown", confidence)
        return LanguageVerdict(detected, "detected", confidence)

    if detected is None or detected == declared:
        return LanguageVerdict(declared, "declared", confidence)

    # Detection disagrees with the human's claim about the feed. It only wins
    # if it is very sure -- see the module docstring.
    if confidence >= OVERRIDE_CONFIDENCE:
        return LanguageVerdict(detected, "detected_over_declared", confidence)
    return LanguageVerdict(declared, "declared", confidence)
