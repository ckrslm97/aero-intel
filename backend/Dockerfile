FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# libpq-dev for psycopg-style builds some deps expect; curl for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# PDF export (Playwright + Chromium) is intentionally not installed here --
# it's a ~300MB optional dependency; the app degrades gracefully without it.
# To enable it: pip install playwright && playwright install --with-deps chromium.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
