import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

_WORDS_PER_MINUTE = 200


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    category: str
    trust_weight: float


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
