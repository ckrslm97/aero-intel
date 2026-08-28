"""Aggregates all v1 routers. Feature routers are added milestone by milestone."""
from fastapi import APIRouter

from app.api.v1 import (
    admin,
    articles,
    biz,
    campaign_alerts,
    editions,
    events,
    health,
    hubs,
    insights,
    kokpit,
    kpis,
    promotions,
    recommendations,
    risks,
    search,
    subscribers,
    taxonomy,
    tk,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(articles.router)
api_router.include_router(biz.router)
api_router.include_router(editions.router)
api_router.include_router(events.router)
api_router.include_router(hubs.router)
api_router.include_router(insights.router)
api_router.include_router(search.router)
api_router.include_router(kokpit.router)
api_router.include_router(kpis.router)
api_router.include_router(promotions.router)
api_router.include_router(campaign_alerts.router)
api_router.include_router(recommendations.router)
api_router.include_router(risks.router)
api_router.include_router(subscribers.router)
api_router.include_router(admin.router)
api_router.include_router(taxonomy.router)
api_router.include_router(tk.router)
