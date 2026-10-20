from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
    reason_code: str | None = None
    sku_id: UUID | None = None
    media_id: UUID | None = None
    comment: str


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    decision_id: UUID | None = None
    product_id: UUID
    seller_id: UUID | None = None
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: ModerationEventType
    occurred_at: datetime
    reviewed_revision: int | None = Field(default=None, ge=1)
    ticket_id: UUID | None = None
    actor_id: UUID | None = None
    action: str | None = Field(default=None, max_length=32)
    reason_code: str | None = Field(default=None, max_length=128)
    comment: str | None = Field(default=None, max_length=4000)
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


class ModerationFieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    reason_code: str
    comment: str
    sku_id: UUID | None = None
    media_id: UUID | None = None


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
    field_reports: list[ModerationFieldReport] = Field(default_factory=list)


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


class AdminModerationFieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=255)
    reason_code: str = Field(min_length=1, max_length=64)
    comment: str = Field(min_length=1, max_length=2000)
    sku_id: UUID | None = None
    media_id: UUID | None = None


class AdminModerationDecisionRequest(BaseModel):
    """Revision-bound decision command sent by Admin over service auth."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    product_id: UUID
    seller_id: UUID | None = None
    submitted_revision: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: int = Field(ge=1)
    action: Literal["APPROVE", "CHANGES_REQUESTED", "REJECT", "HARD_BLOCK"]
    reason_codes: list[str] = Field(default_factory=list, max_length=100)
    field_reports: list[AdminModerationFieldReport] = Field(default_factory=list, max_length=100)
    correlation_id: UUID

    @model_validator(mode="after")
    def validate_action_requirements(self) -> "AdminModerationDecisionRequest":
        if self.action in {"CHANGES_REQUESTED", "REJECT", "HARD_BLOCK"} and not self.reason_codes:
            raise ValueError("non-approval decisions require at least one reason code")
        if self.action == "CHANGES_REQUESTED" and not self.field_reports:
            raise ValueError("change requests require actionable field reports")
        return self
