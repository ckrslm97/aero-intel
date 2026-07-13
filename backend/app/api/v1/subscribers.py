"""Subscriber sign-up. POST is public (a reader-facing signup form), but
listing subscriber emails is PII and admin-only.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_roles
from app.repositories.subscriber_repository import SubscriberRepository
from app.schemas.subscriber import SubscriberCreate, SubscriberOut

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


@router.get("", response_model=list[SubscriberOut], dependencies=[Depends(require_roles("admin"))])
async def list_subscribers(db: AsyncSession = Depends(get_db)) -> list[SubscriberOut]:
    repo = SubscriberRepository(db)
    subscribers = await repo.list_active()
    return [SubscriberOut.model_validate(s) for s in subscribers]


@router.post("", response_model=SubscriberOut, status_code=201)
async def create_subscriber(
    payload: SubscriberCreate, db: AsyncSession = Depends(get_db)
) -> SubscriberOut:
    repo = SubscriberRepository(db)
    existing = await repo.get_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already subscribed")

    subscriber = await repo.create(payload.email)
    await db.commit()
    return SubscriberOut.model_validate(subscriber)
