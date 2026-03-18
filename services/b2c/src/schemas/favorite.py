from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FavoriteAdd(BaseModel):
    product_id: UUID


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    added_at: datetime
