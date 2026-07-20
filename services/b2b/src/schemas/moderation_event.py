from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    idempotency_key: str
    event_type: str
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
            self.blocking_reason_id = self.blocking_reason_id or self.payload.get(
                "blocking_reason_id"
            )
            self.field_reports = self.field_reports or self.payload.get(
                "field_reports",
                [],
            )
        return self
