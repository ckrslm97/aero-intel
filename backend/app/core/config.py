"""Application configuration.

Every external dependency (Redis, Elasticsearch, SMTP, LLM provider) is optional.
When unset, the app falls back to an in-process implementation so the whole
platform boots on a laptop with only Postgres installed.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
    # A cheaper/higher-throughput model for the token-heavy classification calls
    # (categorize/subcategorize send the article body). Empty -> reuse llm_model.
    # On Groq, llama-3.1-8b-instant has a 500k/day token budget vs 100k for the
    # 70b, so routing classification here roughly triples daily throughput while
    # translation (quality-critical) stays on the 70b. See app/llm/factory.py.
    llm_model_fast: str = ""
    llm_base_url: str | None = None  # e.g. http://localhost:11434 for Ollama
    llm_api_key: str | None = None  # OpenAI or Anthropic-compatible key
    # False: spend the LLM only on translation + categorisation, and keep the
    # free local heuristic for summary/sentiment/entities. Even so a live run
    # costs 4 LLM calls per article (categorize, subcategorize, translate x2);
    # the model split above keeps that within Groq's free daily budget for
    # ~140 articles/day. See app/llm/factory.py. Turn on when the key has room.
    llm_full_pipeline: bool = False
    # Cap articles enriched per run so a single scheduled job can't exhaust the
    # LLM's daily budget (see D. jobs-news.yml: 12 runs/day x 12 = ~140/day).
    # Only the live/LLM path is capped; the local heuristic is free and unbounded.
    llm_enrich_batch_size: int = 12

    # --- Email (optional; falls back to writing to ./outbox instead of sending) ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str = "newsroom@aerointel.local"
    outbox_dir: str = "../outbox"

    @field_validator(
        "smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_use_tls",
        "email_from", mode="before"
    )
    @classmethod
    def _empty_env_means_unset(cls, value: object, info) -> object:  # noqa: ANN001 -- pydantic ValidationInfo
        """GitHub Actions renders `${{ secrets.X }}` for a missing secret as an
        EMPTY STRING, not as an unset variable -- which crashed the daily
        edition cron when pydantic tried to parse smtp_port='' as int. Treat
        empty as "not configured": fall back to the field's own default."""
        if isinstance(value, str) and value.strip() == "":
            return cls.model_fields[info.field_name].default
        return value

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
