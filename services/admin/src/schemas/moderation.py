from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared.schemas.events import EventEnvelopeV1
import re


class BlockDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocking_reason_ids: list[UUID] = Field(min_length=1, max_length=20)
    comment: str | None = Field(default=None, max_length=2000)
    field_reports: list["FieldReport"] | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern=r"^(APPROVE|BLOCK|HARD_BLOCK)$")
    reason_code: str | None = Field(default=None, min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=3000)
    claim_token: str = Field(min_length=1)
    product_revision: int = Field(ge=1)


class DecisionResult(BaseModel):
    decision_id: UUID
    status: str
    ticket_id: UUID


class ProductEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=64)
    product_id: UUID
    idempotency_key: str = Field(default="legacy", min_length=1, max_length=128)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", value):
            raise ValueError("event_type must be an uppercase event name")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include timezone")
        return value


class ProductEventEnvelope(EventEnvelopeV1):
    @model_validator(mode="after")
    def validate_product_event(self) -> "ProductEventEnvelope":
        if self.producer != "b2b" or self.aggregate_type != "product":
            raise ValueError("product events must be produced by b2b for product aggregate")
        if self.event_type not in {"product.created", "product.updated", "product.deleted"}:
            raise ValueError("unsupported product event type")
        return self


class FieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1, max_length=255)
    sku_id: UUID | None = None
    comment: str = Field(min_length=1, max_length=2000)


class BlockingReasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    description: str | None = None
    hard_block: bool
    is_active: bool


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    seller_id: UUID | None
    kind: str
    queue_priority: int
    assigned_moderator_id: UUID | None
    status: str
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_card_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": getattr(value, "id"),
                "product_id": getattr(value, "product_id"),
                "seller_id": getattr(value, "seller_id", None),
                "kind": getattr(value, "kind", "CREATE"),
                "queue_priority": getattr(value, "queue_priority", 3),
                "assigned_moderator_id": getattr(value, "moderator_id", None),
                "status": getattr(value, "status"),
                "created_at": getattr(value, "created_at", None),
            }
        if "assigned_moderator_id" not in data and "moderator_id" in data:
            data["assigned_moderator_id"] = data["moderator_id"]
        data["status"] = cls._ticket_status(data.get("status"))
        data["kind"] = cls._ticket_kind(data.get("kind"))
        if not data.get("queue_priority"):
            data["queue_priority"] = 3
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data

    @classmethod
    def _ticket_status(cls, status: object) -> str:
        value = getattr(status, "value", status)
        if value == "MODERATED":
            return "APPROVED"
        return str(value)

    @classmethod
    def _ticket_kind(cls, kind: object) -> str:
        value = getattr(kind, "value", kind)
        if value == "PRODUCT":
            return "CREATE"
        return str(value)


ModerationCardResponse = TicketResponse
