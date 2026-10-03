from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    added_at: datetime
    product: dict[str, object] | None = None


class FavoriteAdd(BaseModel):
    product_id: UUID


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    total_count: int
    limit: int
    offset: int


class ProductSubscriptionRequest(BaseModel):
    notify_on: list[str]


class ProductSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    notify_on: list[str]
    created_at: datetime
