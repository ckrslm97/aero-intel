"""Shared FastAPI dependencies.

Right now this is one thing: the operator gate. AeroIntel has no user accounts
and no login -- it is a single-desk product -- so "admin" here means "whoever
holds the deployment's token", not a role on a user row. That is deliberately
the smallest thing that closes the hole; a real auth system would be a larger
decision than the two endpoints behind this gate justify.
"""
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

# auto_error=False so a missing header reaches us as None and we answer with our
# own message, rather than FastAPI's bare "Not authenticated".
_bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Reject anything without the configured operator token.

    An unset ADMIN_TOKEN denies every request rather than allowing them: an
    operator endpoint that silently opens itself when a deployment forgets to
    set a variable is exactly how /admin/status came to be public in the first
    place. Local development sets the token in .env like any other setting.
    """
    settings = get_settings()
    expected = settings.admin_token

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator endpoints are disabled: ADMIN_TOKEN is not configured.",
        )

    supplied = credentials.credentials if credentials else ""
    # compare_digest over == so a wrong token can't be recovered by timing the
    # response. Both sides are encoded because compare_digest rejects str inputs
    # that aren't ASCII-only, and a token is attacker-supplied.
    if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing operator token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
