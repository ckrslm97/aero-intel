"""Application configuration.

Every external dependency (SMTP, LLM provider) is optional. When unset, the app
falls back to an in-process implementation so the whole platform boots on a
laptop with only Postgres installed.

ADMIN_TOKEN is the one exception: leaving it unset disables the operator
endpoints rather than opening them.
"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "AeroIntel"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    # Bearer token guarding the operator endpoints (/admin/status, subscriber
    # listing). There is no user table and no login: this is a single-desk
    # product, so one deployment secret is the honest shape. Unset -> those
    # endpoints refuse every request. See app/api/deps.py.
    admin_token: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]
    # Where the newsletter's "read on the site" links point. Defaults to the
    # first configured CORS origin at use time (app/email/render.py) so a
    # deployment that already declares its frontend needs no extra setting.
    public_site_url: str | None = None

    # --- Database ---
    database_url: str = "postgresql+asyncpg://localhost:5432/aerointel"

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
    # Local relevance score below which an article is enriched WITHOUT the LLM
    # (see app/pipeline/relevance.py). Ingest brings in 250-700 articles/day
    # against a ~144-article LLM budget, so the budget has to go to the stories
    # this portal is about; everything else still gets a heuristic enrichment
    # and is honestly labelled untranslated. 0 disables the gate.
    llm_relevance_threshold: int = 6

    # --- Pipeline v2 (Phase 7 rebuild) ---
    # Off by default. When true, `python -m app.cli pipeline-v2` runs the new
    # gate -> cluster -> classify -> confidence -> news_events pipeline. It only
    # ever reads status=='enriched' articles and only ever writes event_id,
    # language and news_events -- it never touches `status` or
    # `article_enrichment`, so v1 (still the only thing the site reads) keeps
    # running exactly as before regardless of this flag. The flag exists so the
    # new pipeline can be exercised in a workflow run and compared against v1
    # for days before anything in the product switches over to reading it. See
    # docs/ARCHITECTURE.md.
    pipeline_v2: bool = False

    # --- Campaign intelligence v2 (the campaign-page rebuild) ---
    # Off by default, and read in exactly two places: the deep-scan extraction
    # hook (app/ingest/deep_scan.py) and the article path's campaign fields
    # (app/agents/runner.py). Flag off means byte-for-byte the behaviour that
    # shipped before it existed -- deep_scan records telemetry and extracts
    # nothing, the runner writes the same Promotion columns it always did.
    #
    # It is set to true in .github/workflows/jobs-campaign-deepscan.yml (the
    # official-page path, whose precision the extraction chain was built and
    # measured for) and deliberately NOT in jobs-news.yml: the article path
    # stays off until the golden-set false-positive gate in PR8 says it may be
    # turned on. One flag rather than two because the two paths share the
    # extraction chain, and a half-enabled chain would be a third behaviour
    # nobody tested.
    campaign_v2_enabled: bool = False

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

    # --- External data sources (free) ---
    opensky_base_url: str = "https://opensky-network.org/api"
    yahoo_finance_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"

    # --- Rate limiting ---
    rate_limit_default: str = "120/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()
