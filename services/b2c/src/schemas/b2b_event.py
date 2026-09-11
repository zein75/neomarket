from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class B2BProductEvent(StrEnum):
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    PRODUCT_DELETED = "PRODUCT_DELETED"
    SKU_OUT_OF_STOCK = "SKU_OUT_OF_STOCK"


class ProductEventRequest(BaseModel):
    idempotency_key: UUID
    event: B2BProductEvent
    product_id: UUID
    sku_ids: list[UUID]
    reason: str | None = None
    date: datetime

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if "event" not in data and "event_type" in data:
            data["event"] = data["event_type"]
        if "date" not in data and "occurred_at" in data:
            data["date"] = data["occurred_at"]
        if "product_id" not in data and "product_id" in payload:
            data["product_id"] = payload["product_id"]
        if "sku_ids" not in data:
            if "sku_ids" in payload:
                data["sku_ids"] = payload["sku_ids"]
            elif "sku_id" in payload:
                data["sku_ids"] = [payload["sku_id"]]
        if "reason" not in data and "reason" in payload:
            data["reason"] = payload["reason"]
        return data


class ProductEventResponse(BaseModel):
    accepted: bool = True


class LegacyB2BEventRequest(BaseModel):
    event_type: Literal[
        "PRODUCT_DELETED",
        "PRODUCT_BLOCKED",
        "SKU_OUT_OF_STOCK",
    ]
    idempotency_key: UUID
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
