from uuid import UUID

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class CartItemAdd(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
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
    item_id: UUID | None = None
    product_title: str = ""
    sku_name: str = ""
    image_url: str | None = None
    available_stock: int = 0
    available: bool = False

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
    summary: dict[str, Any] = {}
    checkout_payload: dict[str, Any] = {}

    @computed_field
    @property
    def total(self) -> int:
        return self.subtotal


class CartValidationIssue(BaseModel):
    sku_id: UUID
    issue_type: str
    severity: str
    message: str


class CartValidateResponse(BaseModel):
    is_valid: bool
    can_checkout: bool
    cart: CartResponse | None = None
    issues: list[CartValidationIssue] = []
