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
    event_type: ModerationEventType
    occurred_at: datetime
    product_id: UUID
    hard_block: bool = False
    blocking_reason_id: UUID | None = None
    field_reports: list[dict[str, object]] = Field(default_factory=list)
    payload: dict[str, object] | None = None

    @model_validator(mode="after")
    def flatten_payload(self):
        if self.payload:
            self.hard_block = self.hard_block or bool(self.payload.get("hard_block", False))
            blocking_reason_id = self.payload.get("blocking_reason_id")
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
        return self
