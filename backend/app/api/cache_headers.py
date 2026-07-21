"""Cache-Control for the public read endpoints.

None of this data is per-user and none of it changes between cron runs, but
every response was uncacheable, so each filter click in the newspaper travelled
all the way to Postgres. Vercel honours `s-maxage` at its edge, so a shared
cache absorbs the repeat traffic while `stale-while-revalidate` keeps the first
request after expiry fast too.

Never apply to /admin, /auth or anything user-specific.
"""
from fastapi import Response

# Seconds. The ingest cron runs hourly and the edition job daily, so these are
# all far shorter than the interval at which the underlying data can change.
ARTICLES = 60
AGGREGATES = 300  # counts, insights, kpis -- expensive to compute, cheap to age
CURATED = 600  # TK reviews: changes only on a manual curation pass
STATIC = 3600  # taxonomy, event calendar


def public_cache(response: Response, max_age: int, stale_for: int | None = None) -> None:
    """Mark `response` publicly cacheable for `max_age` seconds.

    Two headers on purpose. CDN-Cache-Control (RFC 9213) is what Vercel's edge
    reads -- verified in production: repeat requests come back
    `x-vercel-cache: HIT` in ~0.3s without touching Python or Neon.

    Measured caveat: Vercel rewrites the *browser-facing* Cache-Control on
    function responses to `public, max-age=0, must-revalidate` no matter what
    we send, so clients always revalidate; they just revalidate against a warm
    edge instead of the database. The plain Cache-Control below is therefore
    for other deployments (the Docker image behind any standard CDN), not for
    Vercel.
    """
    stale = stale_for if stale_for is not None else max_age * 5
    # Vary on Origin, or the edge serves one visitor's CORS answer to everyone.
    # Caught in production: a curl request carrying no Origin header populated
    # the cache for /pivot/dimensions, and every browser afterwards got that
    # copy back -- no Access-Control-Allow-Origin on it, because CORSMiddleware
    # never saw an Origin to answer, so the Analiz page failed to load.
    response.headers["Vary"] = "Origin"
    response.headers["Cache-Control"] = (
        f"public, max-age={max_age}, stale-while-revalidate={stale}"
    )
    response.headers["CDN-Cache-Control"] = (
        f"public, s-maxage={max_age}, stale-while-revalidate={stale}"
    )


def immutable_cache(response: Response) -> None:
    """For content that can never change again -- a past day's edition."""
    response.headers["Cache-Control"] = "public, max-age=86400, immutable"
