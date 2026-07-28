from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModerationEventType(StrEnum):
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    idempotency_key: UUID
    event_type: ModerationEventType | None = None
    occurred_at: datetime
    product_id: UUID
    hard_block: bool = False
    blocking_reason_id: UUID | None = None
    blocking_reason: dict[str, object] | None = None
    field_reports: list[dict[str, object]] = Field(default_factory=list)
    payload: dict[str, object] | None = None

    @model_validator(mode="after")
    def flatten_payload(self):
        if self.event_type is None:
            status_value = self.model_extra.get("status")
            if status_value is None and self.payload:
                status_value = self.payload.get("status")
            if status_value is not None:
                self.event_type = ModerationEventType(str(status_value))
        if self.blocking_reason and self.blocking_reason_id is None:
            reason_id = self.blocking_reason.get("id")
            if reason_id:
                self.blocking_reason_id = (
                    reason_id if isinstance(reason_id, UUID) else UUID(str(reason_id))
                )
        if self.payload:
            self.hard_block = self.hard_block or bool(self.payload.get("hard_block", False))
            payload_reason = self.payload.get("blocking_reason")
            if self.blocking_reason is None and isinstance(payload_reason, dict):
                self.blocking_reason = payload_reason
            blocking_reason_id = self.payload.get("blocking_reason_id")
            if blocking_reason_id is None and isinstance(payload_reason, dict):
                blocking_reason_id = payload_reason.get("id")
            if self.blocking_reason_id is None and blocking_reason_id:
                self.blocking_reason_id = (
                    blocking_reason_id
                    if isinstance(blocking_reason_id, UUID)
                    else UUID(str(blocking_reason_id))
                )
            self.field_reports = self.field_reports or self.payload.get(
                "field_reports",
                [],
            )
        if self.event_type is None:
            raise ValueError("event_type or status is required")
        return self
