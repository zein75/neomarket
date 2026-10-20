from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventEnvelopeV1(BaseModel):
    """Shared validation for all durable inter-service events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: UUID
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,99}$")
    producer: Literal["b2b", "b2c", "admin"]
    aggregate_type: Literal[
        "product", "inventory_order", "order", "moderation_ticket", "brand"
    ]
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1)
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("occurred_at must include a UTC offset")
        return value
