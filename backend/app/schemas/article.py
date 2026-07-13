import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    importance_score: float
    sentiment: str
    confidence_score: float
    corroborating_source_count: int
    verified_at: datetime | None
    tags: str


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


class ArticleListOut(BaseModel):
    total: int
    items: list[ArticleOut]
