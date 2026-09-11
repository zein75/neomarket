from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BlockDecisionRequest(BaseModel):
    blocking_reason_ids: list[UUID] = Field(min_length=1)
    comment: str | None = Field(default=None, max_length=2000)
    field_reports: list[dict[str, object]] = []


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
