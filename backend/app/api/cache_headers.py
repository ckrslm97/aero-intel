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

    Two headers on purpose. Vercel consumes `s-maxage` from Cache-Control and
    then rewrites the browser-facing header to `max-age=0, must-revalidate`
    (verified against production), which would leave the client revalidating on
    every filter click. Targeted caching (RFC 9213) splits the audiences:
    CDN-Cache-Control steers Vercel's edge, Cache-Control is passed through to
    the browser untouched.
    """
    stale = stale_for if stale_for is not None else max_age * 5
    response.headers["Cache-Control"] = (
        f"public, max-age={max_age}, stale-while-revalidate={stale}"
    )
    response.headers["CDN-Cache-Control"] = (
        f"public, s-maxage={max_age}, stale-while-revalidate={stale}"
    )


def immutable_cache(response: Response) -> None:
    """For content that can never change again -- a past day's edition."""
    response.headers["Cache-Control"] = "public, max-age=86400, immutable"
