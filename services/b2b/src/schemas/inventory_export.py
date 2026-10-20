from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InventoryExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["CSV"] = "CSV"
    query: str | None = Field(default=None, max_length=120)
    status: Literal["available", "reserved", "unavailable", "inactive"] | None = None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class InventoryExportResponse(BaseModel):
    id: UUID
    state: Literal["PENDING", "PROCESSING", "READY", "FAILED", "EXPIRED"]
    format: Literal["CSV"] = "CSV"
    row_count: int
    created_at: datetime
    generated_at: datetime | None
    expires_at: datetime | None
    sha256: str | None
    failure_code: str | None
    download_token: str | None = None
