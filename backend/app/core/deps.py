"""FastAPI auth dependencies: decode the bearer JWT, load the user, and gate
routes by role. Role hierarchy is fixed and simple: admin > editor > reader.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if token is None:
        raise _CREDENTIALS_EXCEPTION

    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise _CREDENTIALS_EXCEPTION

    user = await UserRepository(db).get_by_email(payload["sub"])
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION

    return user


def require_roles(*roles: str):
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return _dependency
