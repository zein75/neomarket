from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    parent_id: UUID | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


class CategoryParentResponse(BaseModel):
    id: UUID
    name: str
    slug: str


class CategoryDetailResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    parent: CategoryParentResponse | None = None
    product_count: int | None = None
    seo: dict[str, object]
    meta_tags: dict[str, object]
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
