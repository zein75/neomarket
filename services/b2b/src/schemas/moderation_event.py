from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModerationEventType(StrEnum):
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class BlockingReason(BaseModel):
    # The canonical fields remain explicit.  Moderation may additionally send
    # the already-known reason snapshot so B2B can preserve its real title;
    # this is optional metadata and does not change any required OpenAPI field.
    model_config = ConfigDict(extra="allow")

    id: UUID
    title: str
    comment: str


class FieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The protocol accepts concrete paths such as "images[0]" as well as
    # common field names.
    field_name: str
    sku_id: UUID | None = None
    comment: str


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    product_id: UUID
    status: ModerationEventType
    occurred_at: datetime
    hard_block: bool | None = None
    blocking_reason: BlockingReason | None = None
    field_reports: list[FieldReport] | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ModerationDecisionEvent":
        if self.status is ModerationEventType.BLOCKED:
            if self.hard_block is None:
                raise ValueError("hard_block is required when status is BLOCKED")
            if self.field_reports is None:
                raise ValueError("field_reports is required when status is BLOCKED")
        elif any(
            value is not None
            for value in (self.hard_block, self.blocking_reason, self.field_reports)
        ):
            raise ValueError("blocking fields are only allowed when status is BLOCKED")
        return self


class ModerationEventRequest(BaseModel):
    """Public request schema from the unified B2B Swagger contract."""

    # Optional reason metadata is emitted by the moderation service so B2B can
    # preserve the authoritative seller-facing title without changing any
    # required OpenAPI field.
    model_config = ConfigDict(extra="allow")

    idempotency_key: UUID
    product_id: UUID
    event_type: ModerationEventType
    occurred_at: datetime
    moderator_id: UUID | None = None
    moderator_comment: str | None = None
    blocking_reason_id: UUID | None = None
    hard_block: bool = False
    field_reports: list[FieldReport] = Field(default_factory=list)


    @model_validator(mode="after")
    def validate_blocked_reason(self) -> "ModerationEventRequest":
        if (
            self.event_type is ModerationEventType.BLOCKED
            and self.blocking_reason_id is None
        ):
            raise ValueError("blocking_reason_id is required when event_type is BLOCKED")
        return self
