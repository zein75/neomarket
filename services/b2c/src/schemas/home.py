from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BannerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    image_url: str
    link: str
    priority: int


class BannerListResponse(BaseModel):
    items: list[BannerResponse]
    total_count: int


class BannerEventCreate(BaseModel):
    banner_id: UUID
    event: Literal["impression", "click"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BannerEventsCreate(BaseModel):
    events: list[BannerEventCreate]


class BannerEventsResponse(BaseModel):
    accepted: int
