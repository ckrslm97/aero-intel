# Deployment Guide

## Environment separation

The backend reads config from `backend/.env` via `pydantic-settings`
(`app/core/config.py`). There's no separate `.env.dev`/`.env.staging`/
`.env.prod` convention baked in — instead, point `ENVIRONMENT` at
`development` / `staging` / `production` and inject the rest via your
platform's secrets manager (K8s Secrets, Docker Compose `.env`, your CI/CD
provider's secret store). `ENVIRONMENT=production` disables the verbose
console log renderer in favor of structured JSON logs.

Never commit a real `.env` — `.gitignore` already excludes `backend/.env`,
`frontend/.env.local`, and the root `.env` used by docker-compose.

## Option A: Docker Compose (single host)

```bash
cp .env.example .env   # then edit POSTGRES_PASSWORD, SECRET_KEY, NEXT_PUBLIC_API_URL, etc.
docker compose up -d --build
```

This starts Postgres, Redis, the backend (runs Alembic migrations on boot),
the frontend (standalone Next.js build), and nginx as the reverse proxy in
front of both — reachable at `http://localhost`.

Elasticsearch is **not** started by default (Postgres full-text search covers
the expected article volume); bring it up explicitly if you want it available
for a future search backend swap:

```bash
docker compose --profile search up -d
```

Create the first admin account inside the running backend container:

```bash
docker compose exec backend python -m app.cli create-admin --email you@company.com --password "a-strong-password"
```

PDF export (Playwright + Chromium) is intentionally left out of the backend
image to keep it lean (~120MB browser download). To enable it in a deployed
image, extend `backend/Dockerfile`:

```dockerfile
RUN pip install playwright==1.49.1 && playwright install --with-deps chromium
```

### A note on `NEXT_PUBLIC_API_URL`

Next.js inlines `NEXT_PUBLIC_*` variables into the client bundle **at build
time** — it's not something you can change by just editing `.env` and
restarting the container; the frontend image must be rebuilt. `API_INTERNAL_URL`
(set in `docker-compose.yml`, not build-time) lets server-rendered pages reach
the backend directly over the Docker network instead of bouncing back out
through nginx.

## Option B: Kubernetes

Manifests are in `k8s/` (see `k8s/README.md`) — scaffolded, not wired to a
live cluster. They assume a **managed Postgres and Redis** rather than
running stateful databases in-cluster.

**Important**: keep the backend `Deployment` at `replicas: 1`. The scheduler
(APScheduler) runs in-process; multiple replicas would each independently
fire the same daily ingestion/edition/newsletter jobs, sending duplicate
newsletters. Scale horizontally only after moving scheduled triggers to a
single-leader mechanism (a K8s `CronJob` hitting an internal trigger
endpoint, or Celery Beat with exactly one beat process).

## Database migrations

Alembic migrations live in `backend/alembic/versions/`. Run them as part of
your deploy step, before traffic is routed to new backend pods/containers:

```bash
alembic upgrade head
```

The Docker image's `CMD` already does this on every container start
(`sh -c "alembic upgrade head && uvicorn ..."`) — safe to run repeatedly since
Alembic tracks the current revision and no-ops if there's nothing to apply.

## Monitoring

There's no bundled Prometheus/Grafana stack yet (see `docs/ROADMAP.md`).
`/api/v1/health` and `/api/v1/health/ready` are wired for load-balancer /
Kubernetes liveness/readiness probes today; `/api/v1/admin/status`
(admin-authenticated) surfaces article/edition/subscriber counts, email
delivery status, and scheduler job state for basic operational visibility in
the meantime.

## CI/CD

`.github/workflows/ci.yml` runs backend lint+test (against a real Postgres
service container) and frontend typecheck+lint+build on every push and PR.
It doesn't build/push Docker images or deploy — wire that in once you have a
registry and target environment to push to.
