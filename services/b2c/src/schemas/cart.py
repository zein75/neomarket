from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class CartItemAdd(BaseModel):
    sku_id: UUID
    product_id: UUID
    quantity: int
    unit_price: int  # kopecks


class CartItemUpdate(BaseModel):
    quantity: int


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID
    product_id: UUID
    quantity: int
    unit_price: int

    @computed_field
    @property
    def line_total(self) -> int:
        return self.quantity * self.unit_price


class CartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    session_id: str | None
    currency: str
    items: list[CartItemResponse] = []

    @computed_field
    @property
    def total(self) -> int:
        return sum(item.line_total for item in self.items)
