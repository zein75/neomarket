from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModerationEventType(StrEnum):
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class ModerationField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    PRODUCT_IMAGES = "product_images"
    CATEGORY = "category"
    SKU_NAME = "sku_name"
    SKU_IMAGE = "sku_image"
    SKU_PRICE = "sku_price"


class BlockingReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    comment: str


class FieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: ModerationField
    sku_id: UUID | None = None
    comment: str


class ModerationDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    event_type: ModerationEventType
    occurred_at: datetime
    product_id: UUID
    hard_block: bool = False
    blocking_reason: BlockingReason | None = None
    field_reports: list[FieldReport] = Field(default_factory=list)
