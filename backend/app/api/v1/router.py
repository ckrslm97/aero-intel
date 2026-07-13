"""Aggregates all v1 routers. Feature routers are added milestone by milestone."""
from fastapi import APIRouter

from app.api.v1 import admin, articles, auth, editions, health, ingest, kpis, search, subscribers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(articles.router)
api_router.include_router(ingest.router)
api_router.include_router(editions.router)
api_router.include_router(search.router)
api_router.include_router(kpis.router)
api_router.include_router(subscribers.router)
api_router.include_router(admin.router)
