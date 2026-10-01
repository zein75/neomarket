from datetime import datetime
from uuid import UUID

from typing import Any, Literal

from pydantic import BaseModel, Field


class CartItemAdd(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


class CartItemResponse(BaseModel):
    sku_id: UUID
    product_id: UUID
    name: str
    unit_price: int
    quantity: int
    line_total: int
    available_quantity: int
    is_available: bool
    sku_code: str | None = None
    unit_price_at_add: int | None = None
    image: dict[str, Any] | None = None

    # The published schema is missing this field, while the cart flow requires
    # it for an unavailable line.  It is an enrichment-only value, never a
    # persisted CartItem attribute.
    unavailable_reason: Literal[
        "OUT_OF_STOCK",
        "PRODUCT_BLOCKED",
        "PRODUCT_DELISTED",
        "ON_MODERATION",
    ] | None = None


class CartResponse(BaseModel):
    id: UUID | None = None
    items: list[CartItemResponse]
    items_count: int
    subtotal: int
    is_valid: bool
    updated_at: datetime | None = None


class CartValidationIssue(BaseModel):
    sku_id: UUID
    type: Literal[
        "PRICE_CHANGED",
        "OUT_OF_STOCK",
        "QUANTITY_REDUCED",
        "PRODUCT_BLOCKED",
        "PRODUCT_DELETED",
    ]
    message: str
    old_value: str | int | None = None
    new_value: str | int | None = None


class CartValidateResponse(BaseModel):
    is_valid: bool
    cart: CartResponse
    issues: list[CartValidationIssue] = Field(default_factory=list)
