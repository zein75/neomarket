from datetime import datetime
from uuid import UUID

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CartItemAdd(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: UUID | None = None
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    image_url: str | None = None
    unit_price: int
    quantity: int
    available_stock: int
    line_total: int
    available: bool
    unavailable_reason: Literal[
        "OUT_OF_STOCK",
        "PRODUCT_BLOCKED",
        "PRODUCT_DELISTED",
        "SKU_DISABLED",
        "ON_MODERATION",
        "INSUFFICIENT_STOCK",
    ] | None = None

    # Backward-compatible internal projections are not part of the contract.
    id: UUID | None = None
    name: str | None = None
    unit_price_at_add: int | None = None
    available_quantity: int | None = None
    is_available: bool | None = None
    image: dict[str, Any] | None = None


class CartResponse(BaseModel):
    id: UUID
    items: list[CartItemResponse]
    items_count: int
    subtotal: int
    is_valid: bool
    updated_at: datetime | None = None
    summary: dict[str, Any]
    checkout_payload: dict[str, Any]


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
