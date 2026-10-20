from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.models.order import OrderStatus


class OrderItemSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    quantity: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class CustomerContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=3, max_length=64)


class LegalConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    accepted_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "LegalConsent":
        accepted = self.accepted_at
        if accepted.tzinfo is None or accepted.utcoffset() is None:
            raise ValueError("accepted_at must include a timezone")
        if accepted > datetime.now(timezone.utc):
            raise ValueError("accepted_at cannot be in the future")
        return self


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Canonical checkout fields.
    cart_id: UUID | None = None
    address_id: UUID
    delivery_method: str | None = Field(default=None, max_length=64)
    # Kept for local payment mode compatibility during the v1 rollout.
    payment_method_id: UUID | None = None
    comment: str | None = Field(default=None, max_length=1000)
    items_snapshot: list[OrderItemSnapshot] | None = Field(default=None, max_length=100)
    contact: CustomerContact | None = None
    legal_consents: list[LegalConsent] | None = Field(default=None, max_length=16)
    quote_id: UUID | None = None

    @model_validator(mode="after")
    def validate_checkout_mode(self) -> "OrderCreateRequest":
        if self.delivery_method is None and self.payment_method_id is None:
            raise ValueError("delivery_method is required")
        return self


class CancelOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: UUID
    product_id: UUID
    name: str
    sku_code: str | None = None
    image_url: str | None = None
    quantity: int
    unit_price: int
    line_total: int

    @model_validator(mode="before")
    @classmethod
    def from_order_item_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "sku_id": getattr(value, "sku_id"),
                "product_id": getattr(value, "product_id"),
                "product_title": getattr(value, "product_title", ""),
                "sku_name": getattr(value, "sku_name", ""),
                "quantity": getattr(value, "quantity"),
                "unit_price": getattr(value, "unit_price"),
                "line_total": getattr(value, "line_total"),
            }
        if not data.get("name"):
            parts = [
                str(data.get("product_title") or "").strip(),
                str(data.get("sku_name") or "").strip(),
            ]
            data["name"] = " ".join(part for part in parts if part)
        return data


class OrderAddressResponse(BaseModel):
    id: UUID
    country: str
    region: str | None = None
    city: str
    street: str
    building: str
    apartment: str | None = None
    postal_code: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    is_default: bool | None = None
    comment: str | None = None
    created_at: datetime


class OrderStatusHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: OrderStatus
    changed_at: datetime
    reason: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    buyer_id: UUID
    status: OrderStatus
    subtotal: int
    total: int
    address: OrderAddressResponse
    delivery_method: str | None = None
    cancel_reason: str | None = None
    status_history: list[OrderStatusHistoryResponse] = Field(default_factory=list)
    created_at: datetime
    items: list[OrderItemResponse]
    contact: CustomerContact | None = None
    legal_consents: list[LegalConsent] | None = None
    quote_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def from_order_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            total_amount = getattr(value, "total_amount")
            data = {
                "id": getattr(value, "id"),
                "buyer_id": getattr(value, "user_id"),
                "status": getattr(value, "status"),
                "subtotal": total_amount,
                "total": total_amount,
                "address": getattr(value, "address", {}),
                "address_id": getattr(value, "address_id", None),
                "delivery_method": getattr(value, "delivery_method", None),
                "cancel_reason": getattr(value, "cancel_reason", None),
                "status_history": getattr(value, "status_history", []),
                "created_at": getattr(value, "created_at", None),
                "items": getattr(value, "items", []),
                "contact": getattr(value, "contact", None),
                "legal_consents": getattr(value, "legal_consents", None),
                "quote_id": getattr(value, "quote_id", None),
            }
        if "buyer_id" not in data and "user_id" in data:
            data["buyer_id"] = data["user_id"]
        if "subtotal" not in data and "total_amount" in data:
            data["subtotal"] = data["total_amount"]
        if "total" not in data and "total_amount" in data:
            data["total"] = data["total_amount"]
        # Checkout stores a full address snapshot.  Never manufacture address
        # fields here: it could show a buyer an address unrelated to the order.
        data["address"] = data.get("address") or {}
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data


class OrderPaginatedResponse(BaseModel):
    items: list[OrderResponse]
    total_count: int
    limit: int
    offset: int


class CheckoutOperationStatus(BaseModel):
    operation_id: UUID
    state: str
    order_id: UUID | None = None
    updated_at: datetime
    attempt_id: UUID | None = None
    idempotency_key: UUID | None = None
    error_code: str | None = None


class CheckoutAttemptResponse(BaseModel):
    attempt_id: UUID
    idempotency_key: UUID
    status: str
    order_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None


class OrderDetailItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    quantity: int
    unit_price: int
    line_total: int


class OrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: OrderStatus
    items: list[OrderDetailItemResponse] = []
    total_amount: int
    delivery_address: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_order_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            address = getattr(value, "address", {}) or {}
            data = {
                "id": getattr(value, "id"),
                "status": getattr(value, "status"),
                "items": getattr(value, "items", []),
                "total_amount": getattr(value, "total_amount"),
                "delivery_address": getattr(value, "delivery_address", None),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
            }
            if data["delivery_address"] is None and isinstance(address, dict):
                value = address.get("delivery_address")
                data["delivery_address"] = str(value) if value is not None else None
        now = datetime.now(timezone.utc)
        if data.get("created_at") is None:
            data["created_at"] = now
        if data.get("updated_at") is None:
            data["updated_at"] = data["created_at"]
        return data
