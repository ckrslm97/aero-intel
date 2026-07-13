from datetime import datetime

from pydantic import BaseModel


class SchedulerJobOut(BaseModel):
    id: str
    next_run_time: str | None


class ArticleStatusCountOut(BaseModel):
    status: str
    count: int


class EmailDeliveryStatusCountOut(BaseModel):
    status: str
    count: int


class AdminStatusOut(BaseModel):
    database_ok: bool
    llm_provider: str
    sources_count: int
    articles_by_status: list[ArticleStatusCountOut]
    entities_count: int
    editions_count: int
    latest_edition_date: str | None
    subscribers_count: int
    email_deliveries_by_status: list[EmailDeliveryStatusCountOut]
    latest_article_fetched_at: datetime | None
    scheduler_jobs: list[SchedulerJobOut]
