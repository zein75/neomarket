from typing import Any
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    idempotency_key: str
    event_type: str
    occurred_at: datetime | None = None
    product_id: UUID | None = None
    decision: str | None = None
    status: str | None = None
    hard_block: bool = False
    blocking_reason_id: UUID | None = None
    blocking_reason: dict[str, Any] | None = None
    field_reports: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def flatten_payload(self):
        if self.payload:
            self.product_id = self.product_id or self.payload.get("product_id")
            self.decision = self.decision or self.payload.get("decision")
            self.status = self.status or self.payload.get("status")
            self.hard_block = self.hard_block or bool(self.payload.get("hard_block", False))
            self.blocking_reason_id = self.blocking_reason_id or self.payload.get(
                "blocking_reason_id"
            )
            self.blocking_reason = self.blocking_reason or self.payload.get(
                "blocking_reason"
            )
            self.field_reports = self.field_reports or self.payload.get(
                "field_reports",
                [],
            )
        self.decision = self._decision_from_event_type()
        return self

    def _decision_from_event_type(self) -> str | None:
        event_type = self.event_type.upper()
        if event_type in {"MODERATED", "BLOCKED"}:
            return event_type
        return self.decision or self.status
