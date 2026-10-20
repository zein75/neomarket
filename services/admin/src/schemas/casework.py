from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ComplaintView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    entity_type: Literal["PRODUCT", "SELLER", "MEDIA"]
    entity_id: UUID
    category: str = Field(default=None)
    status: Literal["NEW", "TRIAGED", "IN_REVIEW", "CLOSED", "ESCALATED"]
    priority: int = Field(default=None)
    assigned_to: UUID | None = None
    deadline_at: datetime | None = None
    created_at: datetime = Field(default=None)


class ComplaintAction(BaseModel):
    model_config = ConfigDict(extra="forbid", title="ComplaintAction")

    action: Literal["ASSIGN", "REQUEST_INFO", "WARN", "TEMP_HOLD", "UNPUBLISH", "CLOSE", "ESCALATE"]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str | None = Field(default=None, max_length=3000)
    assignee_staff_id: UUID | None = None


class ComplaintIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    source: Literal["B2C", "SELLER", "ADMIN"]
    reporter_ref: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    entity_type: Literal["PRODUCT", "SELLER", "MEDIA"]
    entity_id: UUID
    category: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    priority: int = Field(default=3, ge=1, le=5)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
