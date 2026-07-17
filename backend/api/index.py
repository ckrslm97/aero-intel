"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module under `api/` exporting an ASGI
callable named `app`. Everything real lives in `app/` -- this is only the
handle Vercel grabs. Deployment-shape differences (no scheduler, no client-side
connection pool, no writable disk) are handled inside the app itself, keyed off
the VERCEL env var; see app/core/db.py and app/main.py.
"""
import sys
from pathlib import Path

# On Vercel the function's working directory is the project root (backend/), but
# it isn't necessarily on sys.path -- make the `app` package importable either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
