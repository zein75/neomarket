from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared.schemas.events import EventEnvelopeV1


class B2BProductEvent(StrEnum):
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    PRODUCT_HARD_BLOCKED = "PRODUCT_HARD_BLOCKED"
    PRODUCT_DELETED = "PRODUCT_DELETED"
    SKU_OUT_OF_STOCK = "SKU_OUT_OF_STOCK"


class ProductEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    event: B2BProductEvent
    product_id: UUID
    sku_ids: list[UUID] = Field(max_length=100)
    reason: str | None = Field(default=None, max_length=1000)
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
        data.pop("payload", None)
        data.pop("event_type", None)
        data.pop("occurred_at", None)
        return data


class ProductEventResponse(BaseModel):
    accepted: bool = True


class CatalogEventEnvelope(EventEnvelopeV1):
    """Public internal contract for B2B product catalog events."""

    @model_validator(mode="after")
    def validate_catalog_scope(self) -> "CatalogEventEnvelope":
        if self.producer != "b2b" or self.aggregate_type != "product":
            raise ValueError("catalog events must be produced by b2b for product aggregate")
        if self.event_type not in {"product.created", "product.updated", "product.deleted", "product.safety_hold.v1"}:
            raise ValueError("unsupported catalog event type")
        return self


class BrandMergeEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_brand_id: UUID
    target_brand_id: UUID
    source_version: int = Field(ge=1)
    target_version: int = Field(ge=1)
    taxonomy_version: int = Field(ge=1)
    product_references_moved: int = Field(ge=0)
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaxonomyEventEnvelope(EventEnvelopeV1):
    """B2B taxonomy events consumed by the read-through B2C catalog."""

    payload: BrandMergeEventPayload

    @model_validator(mode="after")
    def validate_brand_merge_scope(self) -> "TaxonomyEventEnvelope":
        if (
            self.producer != "b2b"
            or self.aggregate_type != "brand"
            or self.event_type != "brand.merged.v1"
            or self.payload.source_brand_id != self.aggregate_id
            or self.payload.source_version != self.aggregate_version
        ):
            raise ValueError("invalid brand merge event scope or version")
        return self


class LegacyB2BEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "PRODUCT_DELETED",
        "PRODUCT_BLOCKED",
        "PRODUCT_HARD_BLOCKED",
        "SKU_OUT_OF_STOCK",
    ]
    idempotency_key: UUID
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
