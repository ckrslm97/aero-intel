# AeroIntel — Deployment (GitHub + Vercel + Neon + Groq)

AeroIntel runs fully automated in the cloud, with nothing on your laptop:

```
Vercel (frontend, Next.js)  ──►  Vercel (backend, FastAPI Python function)  ──►  Neon Postgres
                                                                                    ▲
GitHub Actions (scheduled jobs)  ── CLI commands + Groq API ────────────────────────┘
  • KPIs every 15 min   • news + Turkish translation every 2h
  • daily edition + PDF 04:15 UTC   • maintenance (manual)
```

The backend serves reads/writes on Vercel. All the *writing* work (ingest, enrich,
translate, KPI refresh, PDF render) happens in GitHub Actions, which talk to Neon
directly — Vercel's functions are frozen between requests and can't run schedulers
or Chromium.

Everything below is free-tier. Total cost: **$0**.

---

## 0. Prerequisites

- A GitHub account (the repo is already at `ckrslm97/aero-intel`).
- The `gh` CLI, authenticated (`gh auth login`).
- Accounts you'll create in the steps below: [Neon](https://neon.tech),
  [Groq](https://console.groq.com), [Vercel](https://vercel.com).

---

## 1. Neon Postgres

1. Create a project at [neon.tech](https://neon.tech). Pick a region close to where
   the Actions runners and Vercel functions live (e.g. AWS `eu-central-1`).
2. From the dashboard's **Connection Details**, copy **two** URLs:
   - **Pooled** connection string (host contains `-pooler`) → used by the Vercel
     function at runtime. Pgbouncer transaction mode; the app is already configured
     for it (`NullPool` + disabled prepared-statement cache, see `app/core/db.py`).
   - **Direct** connection string (no `-pooler`) → used by GitHub Actions for
     migrations and batch jobs.

   Both look like `postgresql://user:PASSWORD@host/neondb?sslmode=require`. Keep the
   `?sslmode=require` — the app translates it to asyncpg's `ssl` arg automatically
   (`normalize_database_url`). You do **not** need to add `+asyncpg`; it's added for you.

> Pooled vs direct: the pooled endpoint survives serverless connection churn; the
> direct endpoint is what migrations need (pgbouncer can't run some DDL/session
> features). When in doubt for Actions, use **direct**.

---

## 2. Groq API key

1. Sign in at [console.groq.com](https://console.groq.com) and create an API key
   (starts with `gsk_`).
2. Free-tier budget (per day, per model) that the app is designed around:
   - `llama-3.3-70b-versatile` — 1,000 requests / 100k tokens (best Turkish → translation)
   - `llama-3.1-8b-instant` — 14,400 requests / 500k tokens (→ categorisation)

   The news job enriches at most `LLM_ENRICH_BATCH_SIZE` (12) articles per run, 12
   runs/day ≈ 140 articles/day. With ~382 articles in the DB, the full backlog is
   translated over ~3 days; until then some cards show "otomatik çeviri yok" and stay
   in English — surfaced honestly, never faked.

---

## 3. GitHub secrets

Set these on the repo (values from steps 1–2). `DATABASE_URL` should be the **direct**
Neon URL here — Actions run migrations and batch writes.

```bash
gh secret set DATABASE_URL --repo ckrslm97/aero-intel        # Neon DIRECT url
gh secret set GROQ_API_KEY --repo ckrslm97/aero-intel        # gsk_...
gh secret set SECRET_KEY   --repo ckrslm97/aero-intel        # openssl rand -hex 32

# Optional — only if you want the emailed newsletter (otherwise it's skipped):
gh secret set SMTP_HOST     --repo ckrslm97/aero-intel
gh secret set SMTP_PORT     --repo ckrslm97/aero-intel
gh secret set SMTP_USERNAME --repo ckrslm97/aero-intel
gh secret set SMTP_PASSWORD --repo ckrslm97/aero-intel
gh secret set EMAIL_FROM    --repo ckrslm97/aero-intel

# Optional — only if you'll run the create-admin maintenance task:
gh secret set ADMIN_PASSWORD --repo ckrslm97/aero-intel
```

The repo must be **public** for unlimited Actions minutes (the KPI cron runs every
15 min). Make it public with:

```bash
gh repo edit ckrslm97/aero-intel --visibility public --accept-visibility-change-consequences
```

---

## 4. Vercel — two projects, one repo

Import the same GitHub repo **twice** in Vercel (New Project → import `aero-intel`),
setting a different **Root Directory** each time.

### 4a. Backend project (Root Directory: `backend`)

Vercel auto-detects the Python function via `backend/api/index.py` +
`backend/vercel.json`. Set these **Environment Variables** (Production):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon **pooled** URL (`...-pooler...?sslmode=require`) |
| `SECRET_KEY` | same random string as the GitHub secret |
| `CORS_ORIGINS` | `["https://YOUR-FRONTEND.vercel.app"]` — **JSON array**, fill in after 4b |
| `ENVIRONMENT` | `production` |

`VERCEL=1` is set by the platform automatically — that's what flips the app into
serverless mode (no scheduler, `/tmp` outbox, NullPool). You do **not** set it.

> The backend does **not** need `LLM_*` vars — it only serves reads/writes. All LLM
> work happens in Actions. (If you ever want on-request enrichment, add the same
> `LLM_*` set as jobs-news.yml uses.)

Deploy, then note the backend URL, e.g. `https://aero-intel-backend.vercel.app`.

### 4b. Frontend project (Root Directory: `frontend`)

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://aero-intel-backend.vercel.app/api/v1` |

Deploy, then note the frontend URL. Go back to **4a** and set `CORS_ORIGINS` to
`["https://YOUR-FRONTEND.vercel.app"]`, and redeploy the backend.

---

## 5. First run — migrate + seed (in order)

Run these once, from the **Actions → Maintenance** workflow (Run workflow → pick task),
or locally with the direct URL exported as `DATABASE_URL`:

1. `alembic-upgrade` — create all tables.
2. `seed-kpi-history` — load the verified IATA 2019–2026 series (real trend data).
3. `seed-events` — load the curated events calendar.
4. Then trigger **Actions → News ingest + enrich** once to pull articles + translate,
   and **Actions → KPIs** once to record the first live observations.
5. Optional: **Maintenance → create-admin** (needs `admin_email` input + `ADMIN_PASSWORD`
   secret) for the admin login.

After this, the schedules take over on their own.

---

## 6. Verify production

```bash
# Backend up:
curl -s https://aero-intel-backend.vercel.app/api/v1/kpis | head -c 200

# Today's PDF (after the daily-edition job has run once):
curl -I https://aero-intel-backend.vercel.app/api/v1/editions/$(date -u +%F)/pdf
#   -> 200 application/pdf   (404 = not generated yet; run the daily-edition job)
```

Open the frontend URL: the **Gazete** page should show categorised, mostly-Turkish
news with count badges; **Dashboard** KPIs should have real trend sparklines; the
**Etkinlik** tab should be populated.

---

## Honesty limits / notes

- **GitHub cron is best-effort.** On a free public repo, `*/15` ticks can be delayed or
  skipped under load. Treat cadences as targets, not guarantees.
- **PDF is daily.** It's rendered once a day by the Actions runner (Vercel has no
  Chromium) and served from Postgres. Intra-day news isn't in that day's PDF.
- **Oil price is single-source.** No free second source survived (Stooq's endpoint is
  dead), so there's no cross-check on that one metric — flagged in the UI.
- **Fallback host.** If Vercel's Python runtime ever misbehaves for this stack, the
  backend runs unchanged on [Render](https://render.com) free (same env vars; point the
  frontend's `NEXT_PUBLIC_API_URL` at the Render URL).
