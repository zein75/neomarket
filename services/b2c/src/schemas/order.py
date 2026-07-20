from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.order import OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: UUID
    product_id: UUID
    name: str
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


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    buyer_id: UUID
    status: OrderStatus
    subtotal: int
    total: int
    address: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    currency: str
    items: list[OrderItemResponse] = []

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
        data.setdefault("address", {})
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data
