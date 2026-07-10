from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.moderation import ModerationStatus


class DeclineRequest(BaseModel):
    hard_block: bool = False
    reason: dict[str, object]
    field_reports: list[dict[str, object]] = []


class ModerationCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    moderator_id: UUID | None
    status: ModerationStatus
