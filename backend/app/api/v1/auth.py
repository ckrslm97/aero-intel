from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.limiter import limiter
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserOut:
    repo = UserRepository(db)
    if await repo.get_by_email(payload.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Public signups are always "reader" -- admin/editor accounts are granted
    # by an existing admin (or the create-admin CLI for the first account).
    user = await repo.create(payload.email, payload.password, role="reader")
    await db.commit()
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    repo = UserRepository(db)
    user = await repo.get_by_email(payload.email)
    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(subject=user.email, role=user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
