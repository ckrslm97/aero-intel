# Roadmap

The full spec (see project brief) describes a multi-engineer, multi-month
platform. This build delivers a working end-to-end core and scaffolds the rest
honestly rather than faking it with mock UI.

## Milestones

- [x] **M0 — Scaffold & boot.** Monorepo, config, async DB + Alembic, health
      checks, one-command dev script, design system, dashboard shell.
- [x] **M1 — Ingestion & storage.** RSS adapters for 9 verified free feeds
      (Simple Flying, AirlineGeeks, Aviation Week, ACI, Eurocontrol, Airport
      Technology, FAA, ICAO, Flightradar24 Blog), premium-source stubs
      (IATA/OAG/Cirium/LinkedIn), article persistence, `/articles` API, and a
      live "Today's edition" list page.
- [x] **M2 — Dedup & AI enrichment.** MinHash + LSH near-dup detection (with a
      title-similarity gate so templated recurring reports aren't
      false-matched), pluggable LLM pipeline (Ollama / OpenAI-compatible /
      heuristic fallback with automatic degrade-on-failure), gazetteer entity
      extraction, and cross-source confidence scoring.
- [x] **M3 — Newspaper, archive & search.** Daily edition assembly (Top-10 by
      importance + category sections, AI executive summary), interactive
      `/newspaper/[date]`, `/archive`, and Postgres GIN-indexed full-text
      `/search` wired to the global search bar.
- [x] **M4 — Dashboard KPIs.** Live flights-airborne (OpenSky Network) and
      Brent crude / USD-TRY (Yahoo Finance) refreshed every 15 min; licensed
      metrics (passengers, load factor, cancelled flights) shown as labelled
      estimates, with jet fuel price and daily flight count transparently
      derived from the two real feeds rather than invented.
- [x] **M5 — Email & PDF.** Jinja2 HTML newsletter (dry-run to `./outbox` or
      real SMTP), per-subscriber delivery logs with capped automatic retry,
      and a Playwright-rendered PDF (same template as the email) downloadable
      from both the edition page and the archive.
- [x] **M6 — Auth, scheduler, scaffolds, ops.** JWT auth with three roles
      (admin/editor/reader) gating `/admin`, subscriber listing, and manual
      ingest/rebuild triggers; a real (not placeholder) `/admin` dashboard
      backed by `/admin/status`; a stricter rate limit on `/auth/login`;
      `docker-compose.yml` (Postgres, Redis, backend, frontend, nginx, with
      Elasticsearch behind a profile) and Kubernetes manifests in `k8s/`;
      GitHub Actions CI (backend lint+test against a real Postgres service,
      frontend typecheck+lint+build); regions/airlines/routes/finance/BİZ
      remain the honest frontend-only scaffolds built in M0.
- [x] **M7 — Fund/ETF investment intelligence (`/invest`).** A module
      separate from the aviation content: five US ETFs (XLV, VHT, XLF, XBI,
      ARKG) and four TEFAS funds (AFS, TBE, TI2, MAC), each with 1-year price
      history, holdings (with % weights), and sector/asset-class allocation.
      Data is cross-verified where a second source exists and every row is
      badged with its `verification_status` — `verified` (two sources agreed),
      `official_single_source` (TEFAS, the regulator platform), `single_source`
      (unconfirmed), or `discrepancy` — so unverified data is never shown as
      verified. An economist-style Turkish analysis per fund and per portfolio
      is generated on each refresh via the existing LLM provider abstraction,
      with a deterministic data-grounded fallback and a fixed
      not-investment-advice disclaimer. Adapters
      (`backend/app/ingest/funds/`): Yahoo Finance (price/history, reused from
      the KPI module), SSGA / ARK / Vanguard issuer holdings, TEFAS (new + legacy
      API), stockanalysis.com (price cross-check). Scheduled twice daily
      (07:30 UTC for TEFAS NAVs, 22:30 UTC for the US close). See
      `docs/fund-data-sources.md` for the per-source verification record.

## Deliberately out of scope / stubbed

- **Premium data sources** (IATA, OAG, Cirium, Eurocontrol) and **LinkedIn
  monitoring** are pluggable adapter interfaces (`backend/app/ingest/premium/`),
  not live scrapers — they're licensed or ToS-restricted. Drop in credentials
  and an adapter implementation when available.
- **Kubernetes manifests** are scaffolded (see `k8s/README.md`) but not
  deployed against a live cluster; they assume a managed Postgres/Redis.
- **Prometheus/Grafana** and **Teams/Slack/Discord notifications** are not
  implemented — `/admin/status` covers basic operational visibility for now.
- **Regions, Airlines, Routes, Finance, BİZ** pages are polished frontend
  placeholders (M0) with no backend behind them yet — there's no free data
  source for most of what they'd show (route networks, financial statements,
  regional news taxonomies), so building an API that returns empty/mock data
  would be worse than an honest "coming soon."
