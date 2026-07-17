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
    # Not part of the public payload -- kept only to compute reading time below.
    raw_content: str = Field(exclude=True, repr=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reading_time_minutes(self) -> int:
        word_count = len(self.raw_content.split())
        return max(1, round(word_count / _WORDS_PER_MINUTE))


class ArticleListOut(BaseModel):
    total: int
    items: list[ArticleOut]
