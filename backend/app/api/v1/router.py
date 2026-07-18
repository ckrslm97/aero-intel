"""Aggregates all v1 routers. Feature routers are added milestone by milestone."""
from fastapi import APIRouter

from app.api.v1 import (
    admin,
    articles,
    auth,
    editions,
    events,
    funds,
    health,
    ingest,
    insights,
    kpis,
    search,
    subscribers,
    taxonomy,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(articles.router)
api_router.include_router(ingest.router)
api_router.include_router(editions.router)
api_router.include_router(events.router)
api_router.include_router(insights.router)
api_router.include_router(search.router)
api_router.include_router(kpis.router)
api_router.include_router(funds.router)
api_router.include_router(subscribers.router)
api_router.include_router(admin.router)
api_router.include_router(taxonomy.router)
