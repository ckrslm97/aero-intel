# AeroIntel — Aviation Intelligence Portal

An automated aviation intelligence platform: it ingests news and market data from
trusted aviation sources, verifies it across sources, runs it through an AI
pipeline (dedup → summarize → categorize → extract entities), and produces a
daily digital newspaper — web, PDF, and email — plus a live KPI dashboard and
historical archive.

Built as an internal aviation intelligence portal for a Revenue Management
department. See `docs/ROADMAP.md` for what's live today vs. scaffolded.

## Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Alembic, APScheduler, JWT auth
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind v4, shadcn/ui, Framer Motion, ECharts, Leaflet
- **AI**: pluggable provider abstraction — Ollama, OpenAI-compatible, or a
  no-key heuristic pipeline (extractive summarization, gazetteer entity extraction)
- Redis and Elasticsearch are **optional** — the app falls back to in-process
  caching and Postgres full-text search when they're not configured.

## Quickstart

Requirements: Python 3.11, Node 20+, PostgreSQL running locally. Full details,
troubleshooting, and how to seed data / create an admin account:
**[docs/INSTALL.md](docs/INSTALL.md)**.

```bash
createdb aerointel   # once
./scripts/dev.sh
```

This creates the backend virtualenv, installs frontend dependencies, runs
Alembic migrations, and starts both dev servers:

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000

Configuration lives in `backend/.env` and `frontend/.env.local` (copied from
their `.example` files on first run). Every optional integration — Redis,
Elasticsearch, SMTP, an LLM provider — is unset by default and the app degrades
gracefully; see `backend/.env.example` for how to enable each one.

## Deployment

Docker Compose (Postgres, Redis, backend, frontend, nginx) and Kubernetes
manifests are both included — see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

```bash
cp .env.example .env   # edit POSTGRES_PASSWORD, SECRET_KEY, NEXT_PUBLIC_API_URL
docker compose up -d --build
```

## Auth

JWT-based, with three roles (`admin` / `editor` / `reader`). Public signup
(`POST /auth/register`) always grants `reader`; the first admin is created via
CLI (`python -m app.cli create-admin --email ... --password ...`), and admins
can be promoted further once there's an admin UI for it. `admin` gates
`/admin`, subscriber listing, and manual ingest/rebuild triggers.

## Project layout

```
backend/app/
  core/        config, db, logging, security (JWT), deps (RBAC), cache
  models/      SQLAlchemy ORM (articles, editions, entities, kpis, users, ...)
  ingest/      source adapters (RSS, OpenSky, Yahoo Finance; premium/ stubs for IATA/OAG/Cirium/...)
  pipeline/    dedup, AI enrichment, cross-source verification, edition assembly
  llm/         provider abstraction (Ollama / OpenAI-compatible / heuristic)
  api/v1/      FastAPI routers (auth, admin, articles, editions, kpis, search, ...)
  scheduler/   APScheduler daily automation
  email/ pdf/  newsletter rendering + delivery, PDF export
frontend/src/
  app/         Next.js routes (dashboard, newspaper, archive, admin, login, ...)
  components/  design system, KPI cards, charts, layout shell, auth context
k8s/           Kubernetes manifests (scaffolded, see k8s/README.md)
docker-compose.yml, nginx/, backend/Dockerfile, frontend/Dockerfile
.github/workflows/ci.yml
```

## Tests

Tests run against a real Postgres database (`aerointel_test`) rather than
SQLite, since the models use Postgres-specific types (UUID, JSONB, full-text
search) that SQLite can't represent faithfully.

```bash
createdb aerointel_test   # once
cd backend && source .venv/bin/activate && pytest        # 33 tests
```
