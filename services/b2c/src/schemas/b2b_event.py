from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class B2BEventRequest(BaseModel):
    event_type: Literal[
        "PRODUCT_DELETED",
        "PRODUCT_BLOCKED",
        "SKU_OUT_OF_STOCK",
    ]
    idempotency_key: UUID
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
