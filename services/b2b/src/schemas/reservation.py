from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReserveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    quantity: int = Field(gt=0, le=100)


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    idempotency_key: UUID
    items: list[ReserveItem] = Field(min_length=1, max_length=100)


class UnreserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    items: list[ReserveItem] = Field(min_length=1, max_length=100)


class FulfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    items: list[ReserveItem] | None = Field(default=None, max_length=100)


class InventoryResponse(BaseModel):
    status: str
    order_id: UUID


class InventoryReserveItemResponse(BaseModel):
    sku_id: UUID
    reserved_quantity: int
    remaining_stock: int


class InventoryReserveResponse(InventoryResponse):
    reserved_at: datetime
    reserved: bool = True
    items: list[InventoryReserveItemResponse] = Field(default_factory=list)


class InventoryUnreserveResponse(InventoryResponse):
    processed_at: datetime
    ok: bool = True


class InventoryFulfillResponse(InventoryResponse):
    processed_at: datetime
