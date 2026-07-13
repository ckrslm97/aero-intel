#!/usr/bin/env bash
# One-command local dev bootstrap: migrates the DB, then runs the FastAPI and
# Next.js dev servers together. Requires Postgres running locally; every other
# dependency (Redis, Elasticsearch, SMTP, LLM key) is optional.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  echo "==> Creating backend virtualenv"
  python3.11 -m venv "$BACKEND_DIR/.venv"
  "$BACKEND_DIR/.venv/bin/pip" install --upgrade pip -q
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements-dev.txt" -q
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "==> Creating backend/.env from .env.example"
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi

if [ ! -f "$FRONTEND_DIR/.env.local" ]; then
  echo "==> Creating frontend/.env.local from .env.local.example"
  cp "$FRONTEND_DIR/.env.local.example" "$FRONTEND_DIR/.env.local"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "==> Installing frontend dependencies"
  (cd "$FRONTEND_DIR" && npm install)
fi

echo "==> Running Alembic migrations"
(cd "$BACKEND_DIR" && source .venv/bin/activate && alembic upgrade head)

cleanup() {
  echo "==> Shutting down"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting FastAPI on :8000"
(cd "$BACKEND_DIR" && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

echo "==> Starting Next.js on :3000"
(cd "$FRONTEND_DIR" && npm run dev) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
