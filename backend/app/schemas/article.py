import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.taxonomy import effective_source_tier

_WORDS_PER_MINUTE = 200


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    category: str
    trust_weight: float
    #: The declared column, kept off the wire: `tier` below is what callers
    #: read, and shipping both would invite a client to pick the wrong one.
    declared_tier: str | None = Field(
        default=None, validation_alias="tier", exclude=True, repr=False
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tier(self) -> str:
        """Which rung of the source ladder this outlet sits on -- one of
        app.taxonomy.SOURCE_TIERS.

        The EFFECTIVE tier, not the raw column: `Source.tier` is nullable, and
        a source seeded before that column existed falls back to its
        trust_weight bucket exactly the way the Risk Radarı's publication
        chronology already resolves it (app/pipeline/clustering.py
        tier_for_source, same helper). Never null, so a caller badging a card
        with it needs no fallback of its own -- and never silently "official",
        which only a declared tier can be.
        """
        return effective_source_tier(self.declared_tier, self.trust_weight)


class ArticleEnrichmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    headline: str
    summary: str
    category: str
    subcategory: str | None
    region: str | None
    importance_score: float
    sentiment: str
    confidence_score: float
    corroborating_source_count: int
    verified_at: datetime | None
    tags: str
    headline_tr: str | None
    summary_tr: str | None
    translated_at: datetime | None
    #: low | medium | high, or None for a story the classifier read as carrying
    #: no risk at all. Exposed so a feed row can flag a high-severity story
    #: without a second request to /risks -- Kokpit's "Havacılık Akışı" is the
    #: caller. Null on the great majority of rows and must stay optional to
    #: read: it is a badge a row may earn, never a field a row is expected to
    #: have.
    risk_severity: str | None = None
    #: "Neden önemli?" -- one or two Turkish sentences written by the LLM about
    #: what this story means for a revenue-management desk. Null on nearly
    #: every row by design (see app/models/article.py): it costs a second model
    #: call, so only the day's few highest-scoring stories earn one. The drawer
    #: renders the block when it is present and omits it entirely otherwise --
    #: this is never a field a row is expected to have.
    why_important_tr: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_translated(self) -> bool:
        """True only when a translation-capable LLM actually ran for this
        article (see app/pipeline/enrich.py) -- never implied, always earned."""
        return self.translated_at is not None


class MentionOut(BaseModel):
    """A named entity the article talks about. Carries the IATA code because
    that is what the card needs to draw a carrier's logo."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    code: str | None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str
    author: str | None
    published_at: datetime | None
    fetched_at: datetime
    status: str
    source: SourceOut
    enrichment: ArticleEnrichmentOut | None
    # Stored at ingest. Reading time used to be derived from raw_content, which
    # meant every list request pulled the full article bodies out of Postgres
    # only to discard them -- the list queries now defer that column entirely.
    word_count: int | None = Field(default=None, exclude=True, repr=False)
    # Excluded from the JSON: the shape the client wants is a flat list of
    # airlines and airports, not the association rows.
    entity_links: list = Field(default_factory=list, exclude=True, repr=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reading_time_minutes(self) -> int:
        return max(1, round((self.word_count or 0) / _WORDS_PER_MINUTE))

    def _mentions(self, entity_type: str) -> list[MentionOut]:
        seen: dict[str, MentionOut] = {}
        for link in self.entity_links:
            entity = getattr(link, "entity", None)
            if entity is None or entity.entity_type != entity_type:
                continue
            # An article can link the same carrier twice via different aliases.
            seen.setdefault(entity.name, MentionOut(name=entity.name, code=entity.code))
        return list(seen.values())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def airlines(self) -> list[MentionOut]:
        """Carriers named in the story -- this is what puts a logo on the card.
        Ordered by nothing in particular; the card shows the first few."""
        return self._mentions("airline")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def airports(self) -> list[MentionOut]:
        return self._mentions("airport")


class ArticleListOut(BaseModel):
    total: int
    items: list[ArticleOut]


class ArticleSourceOut(BaseModel):
    """One telling of a story: the canonical article, or one of its duplicates.

    This is what `corroborating_source_count` has always been counting and
    never showed. app/pipeline/verify.py computes confidence from the distinct
    sources across {article} ∪ {its duplicates}, and the drawer printed the
    resulting integer with nothing behind it -- "3 kaynak" that a reader could
    neither check nor open.

    No new data and no new model call: the duplicate group is already stored
    (Article.duplicate_of_id), and this is that group, serialised.
    """

    source_name: str
    #: Effective tier, resolved the same way SourceOut.tier is.
    source_tier: str
    trust_weight: float
    url: str
    published_at: datetime | None
    title: str
    #: True for the canonical article the group is keyed on -- the one the
    #: Gazete actually publishes. The others are the corroboration.
    is_primary: bool
