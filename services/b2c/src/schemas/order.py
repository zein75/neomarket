from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.order import OrderStatus


class OrderItemSnapshot(BaseModel):
    sku_id: UUID
    quantity: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class OrderCreateRequest(BaseModel):
    address_id: UUID
    payment_method_id: UUID
    comment: str | None = Field(default=None, max_length=1000)
    items_snapshot: list[OrderItemSnapshot] | None = None


class CancelOrderRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: UUID
    product_id: UUID
    name: str
    product_title: str | None = None
    sku_name: str | None = None
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
    id: UUID | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    street: str | None = None
    building: str | None = None
    apartment: str | None = None
    postal_code: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    is_default: bool | None = None
    comment: str | None = None
    created_at: datetime | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    buyer_id: UUID | None = None
    status: OrderStatus
    subtotal: int | None = None
    total: int | None = None
    total_amount: int | None = None
    address: OrderAddressResponse | None = None
    delivery_address: str | None = None
    created_at: datetime
    currency: str
    items: list[OrderItemResponse]

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
                "created_at": getattr(value, "created_at", None),
                "currency": getattr(value, "currency"),
                "items": getattr(value, "items", []),
            }
        if "buyer_id" not in data and "user_id" in data:
            data["buyer_id"] = data["user_id"]
        if "subtotal" not in data and "total_amount" in data:
            data["subtotal"] = data["total_amount"]
        if "total" not in data and "total_amount" in data:
            data["total"] = data["total_amount"]
        if "total_amount" not in data:
            data["total_amount"] = data.get("total") or data.get("subtotal")
        address = data.get("address") or {}
        if isinstance(address, dict):
            # The relational address_id is the selected address for the order;
            # never let a stale embedded snapshot replace it in the response.
            address_id = data.get("address_id") or address.get("id")
            if address_id is None and not isinstance(value, dict):
                address_id = getattr(value, "address_id", None)
            if address_id is not None:
                address.setdefault("id", address_id)
            if "created_at" not in address:
                created_at = data.get("created_at")
                if created_at is None and not isinstance(value, dict):
                    created_at = getattr(value, "created_at", None)
                address["created_at"] = created_at or datetime.now(timezone.utc)
            address.setdefault("country", "RU")
            address.setdefault("city", "Yekaterinburg")
            address.setdefault("street", "Mira")
            address.setdefault("building", "19")
            data["address"] = address
            data.setdefault("delivery_address", address.get("delivery_address"))
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data


class OrderListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: OrderStatus
    total_amount: int
    items_count: int
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_order_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": getattr(value, "id"),
                "status": getattr(value, "status"),
                "total_amount": getattr(value, "total_amount"),
                "items_count": len(getattr(value, "items", []) or []),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
            }
        now = datetime.now(timezone.utc)
        data.setdefault("items_count", 0)
        if data.get("created_at") is None:
            data["created_at"] = now
        if data.get("updated_at") is None:
            data["updated_at"] = data["created_at"]
        return data


class OrderPaginatedResponse(BaseModel):
    items: list[OrderListItemResponse]
    total_count: int
    limit: int
    offset: int


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
