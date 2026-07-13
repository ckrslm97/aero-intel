# Installation Guide

## Requirements

- Python 3.11 (the repo was built and tested against this; 3.9/3.10 are not supported —
  some type syntax used here is 3.10+, and 3.11 is what CI runs)
- Node.js 20+
- PostgreSQL 16 (a local install, e.g. `brew install postgresql@16` on macOS)
- Optional: Docker + Docker Compose (for the containerized path — see `docs/DEPLOYMENT.md`)
- Optional: Redis, if you want the cache backend to be shared across processes
  instead of in-memory
- Optional: Ollama (`brew install ollama`) or an OpenAI-compatible API key, if
  you want live LLM output instead of the built-in heuristic pipeline

## 1. Clone and create databases

```bash
git clone <repo-url> aero-intel && cd aero-intel
createdb aerointel
createdb aerointel_test   # only needed to run the backend test suite
```

## 2. One-command bootstrap

```bash
./scripts/dev.sh
```

This creates the backend virtualenv, installs frontend dependencies, copies
`.env.example` → `.env` (backend) and `.env.local.example` → `.env.local`
(frontend) on first run, applies Alembic migrations, and starts both dev
servers:

- Backend: http://localhost:8000 (interactive docs at `/docs`)
- Frontend: http://localhost:3000

Stop with `Ctrl+C` — both processes are cleaned up together.

## 3. Manual setup (if you'd rather not use the script)

```bash
# Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload &

# Frontend
cd ../frontend
cp .env.local.example .env.local
npm install
npm run dev
```

## 4. Seed data and create an admin account

Every optional integration (Redis, Elasticsearch, SMTP, an LLM provider) is
unset by default and the app degrades gracefully — see `backend/.env.example`
for what each one unlocks.

```bash
cd backend && source .venv/bin/activate

# Pull real articles from the 9 built-in free RSS sources
python -m app.cli ingest

# Run the full pipeline once (ingest -> dedup -> AI enrich)
python -m app.cli full-cycle

# Assemble today's newspaper edition
python -m app.cli build-edition

# Pull live OpenSky/Yahoo Finance KPI data
python -m app.cli refresh-kpis

# Create the first admin account (required to view /admin)
python -m app.cli create-admin --email you@company.com --password "a-strong-password"
```

Then visit http://localhost:3000, and sign in at `/login` with the admin
account to see `/admin`.

## 5. Running tests

Tests run against a real Postgres database (`aerointel_test`), not SQLite —
the models use Postgres-specific types (UUID, JSONB, GIN-indexed full-text
search) that SQLite can't represent faithfully.

```bash
cd backend && source .venv/bin/activate && pytest        # 33 tests
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Troubleshooting

- **`FAA` source returns a 403 in the logs**: expected — their feed blocks our
  user-agent. The ingestion run continues; every other source is unaffected.
- **`ICAO` source returns 0 articles**: their feed occasionally serves an
  empty payload; also handled gracefully.
- **Playwright/PDF errors**: PDF export needs `playwright install chromium`
  (already in `requirements-dev.txt`, but the browser binary is a separate
  ~120MB download). If it's not installed, PDF generation logs a warning and
  skips itself — the rest of the pipeline is unaffected.
