from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AppealView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    original_decision_id: UUID
    reviewer_staff_id: UUID | None = None
    status: Literal["SUBMITTED", "TRIAGED", "IN_REVIEW", "UPHELD", "OVERTURNED", "PARTIALLY_UPHELD", "CLOSED"]
    created_at: datetime = Field(default=None)


class AppealAction(BaseModel):
    model_config = ConfigDict(extra="forbid", title="AppealAction")

    outcome: Literal["UPHELD", "OVERTURNED", "PARTIALLY_UPHELD"]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str = Field(max_length=3000)


class AppealIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    original_decision_id: UUID
    claimant_ref: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
