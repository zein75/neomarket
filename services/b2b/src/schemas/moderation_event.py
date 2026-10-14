from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from shared.schemas.events import EventEnvelopeV1


class ModerationEventType(StrEnum):
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class BlockingReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ModerationDecisionEvent":
        if self.status is ModerationEventType.BLOCKED:
            if self.hard_block is None:
                raise ValueError("hard_block is required when status is BLOCKED")
        elif any(
            value is not None
            for value in (self.hard_block, self.blocking_reason, self.field_reports)
        ):
            raise ValueError("blocking fields are only allowed when status is BLOCKED")
        return self


class ModerationEventRequest(BaseModel):
    """Public request schema from the unified B2B Swagger contract."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    product_id: UUID
    event_type: ModerationEventType
    occurred_at: datetime
    moderator_id: UUID | None = None
    moderator_comment: str | None = None
    blocking_reason_id: UUID | None = None
    hard_block: bool = False
    field_reports: list[FieldReport] | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_blocked_reason(self) -> "ModerationEventRequest":
        if (
            self.event_type is ModerationEventType.BLOCKED
            and self.blocking_reason_id is None
        ):
            raise ValueError("blocking_reason_id is required when event_type is BLOCKED")
        return self


class ModerationEnvelopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    reviewed_revision: int
    decision_id: UUID
    ticket_id: UUID
    actor_id: UUID
    action: str
    reason_code: str | None = None
    comment: str | None = None


class ModerationEventEnvelope(EventEnvelopeV1):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    producer: str = "admin"
    aggregate_type: str = "moderation_ticket"
    payload: ModerationEnvelopePayload

    @model_validator(mode="after")
    def validate_moderation_event(self) -> "ModerationEventEnvelope":
        if self.producer != "admin" or self.aggregate_type != "moderation_ticket":
            raise ValueError("invalid moderation event producer or aggregate type")
        if self.event_type not in {
            "moderation.approved",
            "moderation.blocked",
            "moderation.hard_blocked",
        }:
            raise ValueError("unsupported moderation event type")
        if self.payload.action not in {"APPROVE", "BLOCK", "HARD_BLOCK"}:
            raise ValueError("unsupported moderation action")
        return self
