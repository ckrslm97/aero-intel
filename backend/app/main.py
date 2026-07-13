"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.environment, llm_provider=settings.llm_provider)
    if settings.scheduler_enabled:
        from app.scheduler.jobs import start_scheduler, stop_scheduler

        start_scheduler()
        yield
        stop_scheduler()
    else:
        yield
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Automated aviation intelligence portal: daily newspaper, dashboard, and archive.",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict:
    return {"name": settings.app_name, "status": "running", "docs": "/docs"}
