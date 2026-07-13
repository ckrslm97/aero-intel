"""Application configuration.

Every external dependency (Redis, Elasticsearch, SMTP, LLM provider) is optional.
When unset, the app falls back to an in-process implementation so the whole
platform boots on a laptop with only Postgres installed.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "AeroIntel"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    secret_key: str = Field(default="dev-insecure-secret-change-me")
    access_token_expire_minutes: int = 60 * 12
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Database ---
    database_url: str = "postgresql+asyncpg://localhost:5432/aerointel"

    # --- Cache / queue (optional; falls back to in-process memory cache) ---
    redis_url: str | None = None

    # --- Search (optional; falls back to Postgres full-text search) ---
    elasticsearch_url: str | None = None

    # --- LLM provider (optional; falls back to heuristic/no-key pipeline) ---
    llm_provider: Literal["heuristic", "ollama", "openai_compat"] = "heuristic"
    llm_model: str = "llama3.1"
    llm_base_url: str | None = None  # e.g. http://localhost:11434 for Ollama
    llm_api_key: str | None = None  # OpenAI or Anthropic-compatible key

    # --- Email (optional; falls back to writing to ./outbox instead of sending) ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str = "newsroom@aerointel.local"
    outbox_dir: str = "../outbox"

    # --- Storage ---
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "../storage"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # --- External data sources (free) ---
    opensky_base_url: str = "https://opensky-network.org/api"
    yahoo_finance_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"

    # --- Scheduler ---
    scheduler_enabled: bool = True
    daily_edition_hour_utc: int = 4  # newspaper assembled 04:00 UTC daily
    daily_newsletter_hour_utc: int = 5

    # --- Rate limiting ---
    rate_limit_default: str = "120/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()
