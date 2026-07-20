from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class ReserveItem(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)


class ReserveRequest(BaseModel):
    order_id: UUID
    idempotency_key: str
    items: list[ReserveItem] = Field(min_length=1)


class UnreserveRequest(BaseModel):
    order_id: UUID
    items: list[ReserveItem] | None = None


class FulfillRequest(BaseModel):
    order_id: UUID


class InventoryResponse(BaseModel):
    status: str
    order_id: UUID


class InventoryReserveResponse(InventoryResponse):
    reserved_at: datetime


class InventoryUnreserveResponse(InventoryResponse):
    processed_at: datetime


class InventoryFulfillResponse(InventoryResponse):
    processed_at: datetime
