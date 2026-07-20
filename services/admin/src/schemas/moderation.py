from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class DeclineRequest(BaseModel):
    hard_block: bool = False
    reason: dict[str, object]
    field_reports: list[dict[str, object]] = []


class ModerationCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    seller_id: UUID | None
    kind: str
    queue_priority: int
    moderator_id: UUID | None
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
                "kind": getattr(value, "kind", "PRODUCT"),
                "queue_priority": getattr(value, "queue_priority", 0),
                "moderator_id": getattr(value, "moderator_id", None),
                "status": getattr(value, "status"),
                "created_at": getattr(value, "created_at", None),
            }
        data["status"] = cls._ticket_status(data.get("status"))
        data.setdefault("kind", "PRODUCT")
        data.setdefault("queue_priority", 0)
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data

    @classmethod
    def _ticket_status(cls, status: object) -> str:
        value = getattr(status, "value", status)
        if value == "MODERATED":
            return "APPROVED"
        if value in {"BLOCKED", "HARD_BLOCKED"}:
            return "REJECTED"
        return str(value)
