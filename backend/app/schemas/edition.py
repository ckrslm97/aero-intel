import uuid
from datetime import date

from pydantic import BaseModel

from app.schemas.article import ArticleOut


class EditionSectionOut(BaseModel):
    section: str
    articles: list[ArticleOut]


class EditionOut(BaseModel):
    id: uuid.UUID
    edition_date: date
    status: str
    headline: str
    executive_summary: str
    sections: list[EditionSectionOut]
    pdf_available: bool


class EditionSummaryOut(BaseModel):
    """Lightweight edition metadata for the archive list -- no article bodies."""

    id: uuid.UUID
    edition_date: date
    status: str
    headline: str
    story_count: int
    pdf_available: bool
