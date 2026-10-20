from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_id: UUID
    permission: str = Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    scope: str = Field(default="global", min_length=1, max_length=255)
    expires_at: datetime | None = None
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value == "global":
            return value
        if value.startswith("seller:"):
            try:
                return f"seller:{UUID(value.removeprefix('seller:'))}"
            except ValueError as exc:
                raise ValueError("seller scope must contain a UUID") from exc
        raise ValueError("scope must be global or seller:<UUID>")

    @field_validator("expires_at")
    @classmethod
    def require_expiry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must include timezone information")
        return value


class PermissionGrantRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class ReasonAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str | None = Field(default=None, max_length=3000)


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra="forbid", title="ReasonInput")

    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    severity: str = Field(pattern=r"^(INFO|FIX_REQUIRED|REJECT|HARD_BLOCK)$")
    active: bool = True


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    rules: dict[str, object]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class PublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    approved_by: UUID | None = None
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class RuntimeSettingsProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    values: dict[str, int | float]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class AuditExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime
    reason_code: str

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit export timestamps must include timezone information")
        return value


class AdminOperationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    status: Literal["QUEUED", "RUNNING", "WAITING_APPROVAL", "APPLIED", "PARTIAL", "FAILED", "CANCELLED"]
    resource_id: UUID = Field(default=None)
    request_id: str
    updated_at: datetime = Field(default=None)
    version: int = Field(exclude=True)


class OperationReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    request_id: str
    action: str
    status: Literal["QUEUED", "RUNNING", "WAITING_APPROVAL", "APPLIED", "PARTIAL", "FAILED", "CANCELLED"]
    entity_type: str
    resource_id: UUID
    requested_by_staff_id: UUID
    approved_by_staff_id: UUID | None = None
    cancelled_by_staff_id: UUID | None = None
    reason_code: str
    created_at: datetime
    updated_at: datetime
    version: int = Field(exclude=True)
    summary: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)
    approval_supported: bool
