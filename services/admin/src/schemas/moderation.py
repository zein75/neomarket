from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared.schemas.events import EventEnvelopeV1
import re


class BlockDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocking_reason_ids: list[UUID] = Field(min_length=1, max_length=20)
    comment: str | None = Field(default=None, max_length=2000)
    field_reports: list["FieldReport"] | None = None


class DecisionFieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=255)
    sku_id: UUID | None = None
    media_id: UUID | None = None
    reason_code: str = Field(min_length=1, max_length=64)
    comment: str = Field(min_length=1, max_length=2000)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", title="DecisionInput")

    action: Literal["APPROVE", "CHANGES_REQUESTED", "REJECT", "HARD_BLOCK", "ESCALATE"]
    claim_token: str = Field(min_length=32, max_length=256)
    product_revision: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    passed_rules: list[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]] = Field(default_factory=list, max_length=30)
    field_reports: list[DecisionFieldReport] = Field(default_factory=list, max_length=100)
    comment: str | None = Field(default=None, max_length=3000)
    policy_version: int = Field(ge=1)

    @field_validator("passed_rules")
    @classmethod
    def validate_passed_rules(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("passed_rules must not contain duplicates")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", rule) for rule in value):
            raise ValueError("passed_rules entries must be stable uppercase rule codes")
        return value

    @model_validator(mode="after")
    def require_passed_rules_for_approval(self) -> "DecisionInput":
        if self.action == "APPROVE" and not self.passed_rules:
            raise ValueError("APPROVE requires at least one passed rule")
        if self.action != "APPROVE" and self.passed_rules:
            raise ValueError("passed_rules may only be supplied for APPROVE")
        return self


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    operation_id: UUID
    status: Literal["DECISION_PENDING", "DECIDED", "RECONCILIATION_REQUIRED"]
    ticket_id: UUID


class AuditEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    action: str
    actor_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    created_at: datetime
    request_id: str | None = None
    redacted_details: dict[str, object] | None = None


class PageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_cursor: str | None = Field(default=None)
    has_more: bool


class AuditPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEventView]
    page: PageView


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: "TicketResponse"
    claim_token: str
    lease_expires_at: datetime
    fencing_version: int = Field(ge=1)


class LeaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_token: str = Field(min_length=32, max_length=256)
    fencing_version: int = Field(ge=1)


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
        if self.event_type not in {
            "product.created",
            "product.updated",
            "product.deleted",
            "product.publication.applied.v1",
            "product.publication.rejected.v1",
        }:
            raise ValueError("unsupported product event type")
        return self


class PublicationDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    product_id: UUID
    submitted_revision: int = Field(ge=1)
    action: Literal["APPROVE", "CHANGES_REQUESTED", "REJECT", "HARD_BLOCK"]
    published_revision: int | None = Field(default=None, ge=1)
    visible: bool | None = None
    reason_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]{0,63}$",
    )


class PublicationDecisionEnvelope(EventEnvelopeV1):
    model_config = ConfigDict(extra="forbid")

    payload: PublicationDecisionPayload

    @model_validator(mode="after")
    def validate_publication_decision(self) -> "PublicationDecisionEnvelope":
        if self.producer != "b2b" or self.aggregate_type != "product":
            raise ValueError("publication decisions must be produced by b2b for product aggregate")
        if self.event_type not in {
            "product.publication.applied.v1",
            "product.publication.rejected.v1",
        }:
            raise ValueError("unsupported publication decision event")
        if self.aggregate_id != self.payload.product_id:
            raise ValueError("publication decision product does not match aggregate_id")
        if (
            self.event_type == "product.publication.applied.v1"
            and self.aggregate_version != self.payload.submitted_revision
        ):
            raise ValueError("applied publication version must match the submitted revision")
        if (
            self.event_type == "product.publication.rejected.v1"
            and self.aggregate_version < self.payload.submitted_revision
        ):
            raise ValueError("rejected publication version cannot precede the submitted revision")
        if self.event_type == "product.publication.rejected.v1" and not self.payload.reason_code:
            raise ValueError("rejected publication decisions require a reason_code")
        if (
            self.event_type == "product.publication.applied.v1"
            and self.payload.action == "APPROVE"
            and self.payload.published_revision != self.payload.submitted_revision
        ):
            raise ValueError("applied approvals must identify the published submitted revision")
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
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    product_id: UUID
    seller_id: UUID | None = None
    kind: Literal["CREATE", "UPDATE", "MEDIA_UPDATE", "CATEGORY_CHANGE", "RECHECK", "REPORT", "APPEAL"]
    status: Literal["NEW", "IN_REVIEW", "WAITING_SELLER", "ESCALATED", "DECISION_PENDING", "DECIDED", "STALE", "CANCELLED"]
    priority: int = Field(default=3, ge=0, le=5)
    assigned_to: UUID | None = None
    created_at: datetime
    submitted_revision: int = Field(ge=1)
    snapshot_hash: str
    version: int = Field(ge=1)
    lease_expires_at: datetime | None = None
    deadline_at: datetime | None = None

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
                "submitted_revision": getattr(value, "submitted_revision", None),
                "snapshot_hash": getattr(value, "snapshot_hash", None),
                "version": getattr(value, "version", 1),
                "lease_expires_at": getattr(value, "lease_expires_at", None),
            }
        if "priority" not in data:
            data["priority"] = data.pop("queue_priority", 3)
        if "assigned_to" not in data:
            data["assigned_to"] = data.pop("assigned_moderator_id", data.get("moderator_id"))
        data.pop("moderator_id", None)
        data.pop("assigned_moderator_id", None)
        data["status"] = cls._ticket_status(data.get("status"))
        data["kind"] = cls._ticket_kind(data.get("kind"))
        if data.get("priority") is None:
            data["priority"] = 3
        if data.get("created_at") is None:
            data["created_at"] = datetime.now(timezone.utc)
        return data

    @classmethod
    def _ticket_status(cls, status: object) -> str:
        value = getattr(status, "value", status)
        if value in {"CREATED", "PENDING"}:
            return "NEW"
        if value == "MODERATED":
            return "DECISION_PENDING"
        if value in {"BLOCKED", "HARD_BLOCKED"}:
            return "DECIDED"
        return str(value)

    @classmethod
    def _ticket_kind(cls, kind: object) -> str:
        value = getattr(kind, "value", kind)
        if value == "PRODUCT":
            return "CREATE"
        return str(value)


# ClaimResult is declared before TicketResponse for readability in the request
# schemas above; resolve the response reference explicitly at import time.
ClaimResult.model_rebuild()

ModerationCardResponse = TicketResponse
