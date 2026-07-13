import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class SubscriberCreate(BaseModel):
    email: EmailStr


class SubscriberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_active: bool
