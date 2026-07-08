from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReservationCreate(BaseModel):
    sku_id: UUID
    order_id: UUID
    quantity: int


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID
    order_id: UUID
    quantity: int
