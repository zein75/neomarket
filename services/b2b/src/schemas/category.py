from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field


class CategoryAttributeSchema(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    required: bool = False
    value_type: Literal["text", "number", "select"] = "text"
    options: list[str] = Field(default_factory=list, max_length=100)
    allowed_units: list[str] = Field(default_factory=list, max_length=30)


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    parent_id: UUID | None = None
    is_active: bool
    attribute_schema: list[CategoryAttributeSchema] = Field(default_factory=list)
    revision: int = 1
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
    product_count_as_of: datetime | None = None
    seo: dict[str, object]
    meta_tags: dict[str, object]
    image_url: str | None = None
    is_active: bool
    attribute_schema: list[CategoryAttributeSchema] = Field(default_factory=list)
    revision: int = 1
    created_at: datetime
    updated_at: datetime
