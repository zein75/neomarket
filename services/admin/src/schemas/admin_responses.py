from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator

from .admin import AdminOperationResponse, OperationReviewResponse
from .appeals import AppealView
from .casework import ComplaintView
from .moderation import TicketResponse


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageResponse(StrictResponse):
    next_cursor: str | None = None
    has_more: bool


class CaseTimelineEntry(StrictResponse):
    event_id: UUID
    action: str
    actor_id: UUID | None = None
    occurred_at: datetime
    reason_code: str | None = None
    operation_id: UUID | None = None
    assigned_to: UUID | None = None
    outcome: str | None = None


class ComplaintDetail(ComplaintView):
    timeline: list[CaseTimelineEntry]


class ComplaintEvidenceResponse(StrictResponse):
    complaint_id: UUID
    evidence_refs: list[Annotated[str, Field(pattern=r"^[A-Fa-f0-9]{64}$")]] = Field(max_length=20)
    scan_status: Literal["NOT_CONFIGURED"]


class AppealEvidenceResponse(StrictResponse):
    appeal_id: UUID
    evidence_refs: list[Annotated[str, Field(pattern=r"^[A-Fa-f0-9]{64}$")]] = Field(max_length=20)
    scan_status: Literal["NOT_CONFIGURED"]


class OriginalDecisionResponse(StrictResponse):
    decision_id: UUID
    ticket_id: UUID
    actor_id: UUID
    action: str
    product_revision: int | None = Field(default=None, ge=1)
    snapshot_hash: str | None = None
    policy_version: int | None = Field(default=None, ge=1)
    reason_codes: list[str] | None = None
    passed_rules: list[str] | None = None
    decided_at: datetime


class AppealDetail(AppealView):
    timeline: list[CaseTimelineEntry]
    original_decision: OriginalDecisionResponse


class PrincipalResponse(StrictResponse):
    staff_id: UUID
    display_name: str | None = None
    roles: list[str]
    permissions: list[str]
    mfa_verified: bool
    session_expires_at: datetime | None = None


class ModeratorWorkloadResponse(StrictResponse):
    staff_id: UUID
    in_review: int = Field(ge=0)


class DashboardMetricsResponse(StrictResponse):
    as_of: datetime
    provenance: dict[str, str]
    workload_by_moderator: list[ModeratorWorkloadResponse]
    pending: int = Field(ge=0)
    in_review: int = Field(ge=0)
    overdue: int = Field(ge=0)
    complaints_pending: int = Field(ge=0)
    complaints_in_review: int = Field(ge=0)
    complaints_overdue: int = Field(ge=0)
    average_resolution_seconds: float | None = Field(default=None, ge=0)
    resolved_decision_count: int = Field(ge=0)
    oldest_pending_seconds: int | None = Field(default=None, ge=0)
    oldest_complaint_pending_seconds: int = Field(ge=0)
    outbox_pending: int | None = Field(default=None, ge=0)
    outbox_dead: int | None = Field(default=None, ge=0)


class IntegrationCapabilityResponse(StrictResponse):
    key: Literal[
        "identity_provider",
        "mfa_step_up",
        "b2b_admin_api",
        "seller_kyc",
        "evidence_av_scan",
        "case_notice_delivery",
        "payment_disputes",
        "delivery_logs",
    ]
    status: Literal["CONFIGURED_UNVERIFIED", "NOT_CONFIGURED"]
    blocked_actions: list[str]
    detail: str


class IntegrationStatusResponse(StrictResponse):
    as_of: datetime
    items: list[IntegrationCapabilityResponse]


class RuntimeSettingSectionResponse(StrictResponse):
    key: Literal["queue_policy", "workflow_settings", "deployment_settings", "moderation_sla", "safety_hold_policy", "notification_settings", "retention_status"]
    status: Literal["CONFIGURED_VERSIONED", "CONFIGURED_UNVERSIONED", "NOT_CONFIGURED", "BLOCKED_PENDING_DECISION"]
    source: Literal["database", "environment", "none"]
    version: int | None = Field(default=None, ge=1)
    writable: bool
    values: dict[str, int | float | bool | str | None]
    detail: str


class RuntimeSettingsResponse(StrictResponse):
    as_of: datetime
    items: list[RuntimeSettingSectionResponse]


class TicketPageResponse(StrictResponse):
    items: list[TicketResponse]
    page: PageResponse


class SnapshotImageResponse(StrictResponse):
    media_id: UUID | None = None
    url: AnyUrl = Field(default=None)
    status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_media_reference(cls, value: object) -> object:
        if isinstance(value, str):
            return {"url": value}
        if isinstance(value, dict):
            data = dict(value)
            data.setdefault("media_id", data.pop("id", None))
            return {key: data[key] for key in ("media_id", "url", "status") if key in data}
        return value


class SnapshotSkuResponse(StrictResponse):
    sku_id: UUID | None = None
    name: str | None = None
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    attributes: dict[str, Any] | None = None
    images: list[SnapshotImageResponse] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_sku_snapshot(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("sku_id", data.pop("id", None))
        data.setdefault("price_minor", data.pop("price", None))
        data.setdefault("attributes", data.pop("options", None))
        return {
            key: data[key]
            for key in ("sku_id", "name", "price_minor", "currency", "attributes", "images")
            if key in data
        }


class ProductSnapshotResponse(StrictResponse):
    product_id: UUID
    seller_id: UUID | None = None
    revision: int = Field(ge=1)
    snapshot_hash: str
    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    images: list[SnapshotImageResponse] = Field(default_factory=list)
    skus: list[SnapshotSkuResponse]
    attributes: dict[str, Any]
    policy_version: int = Field(ge=1)


class FieldDiffResponse(StrictResponse):
    path: str | None = None
    before: Any = None
    after: Any = None


class ChecklistItemResponse(StrictResponse):
    code: str | None = None
    passed: bool | None = None
    message: str | None = None


class TicketHistoryItemResponse(StrictResponse):
    action: str | None = None
    actor_id: UUID | None = None
    occurred_at: datetime | None = None


class TicketDetailResponse(StrictResponse):
    ticket: TicketResponse
    snapshot: ProductSnapshotResponse
    published_revision: int | None = Field(default=None, ge=1)
    field_diff: list[FieldDiffResponse] | None = None
    checklist: list[ChecklistItemResponse]
    history: list[TicketHistoryItemResponse] | None = None


class ReasonResponse(StrictResponse):
    id: UUID
    code: str
    title: str
    description: str | None = None
    severity: Literal["INFO", "FIX_REQUIRED", "REJECT", "HARD_BLOCK"]
    active: bool
    policy_version: int | None = Field(default=None, ge=1)


class ReasonPageResponse(StrictResponse):
    items: list[ReasonResponse]
    page: PageResponse


class ComplaintPageResponse(StrictResponse):
    items: list[ComplaintView]
    page: PageResponse


class AppealPageResponse(StrictResponse):
    items: list[AppealView]
    page: PageResponse


class OperationPageResponse(StrictResponse):
    items: list[AdminOperationResponse]
    page: PageResponse


class OperationReviewPageResponse(StrictResponse):
    items: list[OperationReviewResponse]
    page: PageResponse


class OutboxEventResponse(StrictResponse):
    id: UUID
    event_type: str
    status: str
    attempts: int | None = Field(default=None, ge=0)
    last_error: str | None = None
    created_at: datetime | None = None


class OutboxPageResponse(StrictResponse):
    items: list[OutboxEventResponse]
    page: PageResponse


class StaffGrantResponse(StrictResponse):
    grant_id: UUID
    permission: str | None = None
    role: str | None = None
    scope: str
    expires_at: datetime | None = None
    granted_by: UUID | None = None


class StaffProfileResponse(StrictResponse):
    staff_id: UUID
    oidc_issuer: str | None = None
    display_name: str | None = None
    roles: list[str]
    permissions: list[str]
    status: str
    version: int = Field(ge=1)
    grants: list[StaffGrantResponse]


class StaffPageResponse(StrictResponse):
    items: list[StaffProfileResponse]
    page: PageResponse


class PolicyResponse(StrictResponse):
    id: UUID
    code: str
    version: int = Field(ge=1)
    status: str
    effective_at: datetime | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PolicyPageResponse(StrictResponse):
    items: list[PolicyResponse]
    page: PageResponse
