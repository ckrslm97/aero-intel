"""Shared slowapi Limiter instance -- lives outside main.py so route modules
can apply per-route limits (e.g. a stricter cap on /auth/login) without a
circular import back into the app entrypoint.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().rate_limit_default])
