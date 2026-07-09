from uuid import UUID

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class CartItemAdd(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)
    product_id: UUID | None = None
    unit_price: int | None = None  # legacy price-at-add, not used for totals


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: UUID
    product_id: UUID | None = None
    name: str | None = None
    quantity: int
    unit_price: int = 0
    unit_price_at_add: int | None = None
    available_quantity: int = 0
    is_available: bool = False
    unavailable_reason: str | None = None
    image: dict[str, Any] | None = None

    @computed_field
    @property
    def line_total(self) -> int:
        if not self.is_available:
            return 0
        return self.quantity * self.unit_price


class CartResponse(BaseModel):
    id: UUID | str
    user_id: UUID | None
    session_id: str | None
    currency: str
    items: list[CartItemResponse] = []
    items_count: int = 0
    subtotal: int = 0
    is_valid: bool = True

    @computed_field
    @property
    def total(self) -> int:
        return self.subtotal
