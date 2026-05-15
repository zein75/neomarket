from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.product import ProductStatus
from src.schemas.sku import SKUResponse


class ProductCreate(BaseModel):
    title: str
    description: str | None = None
    category_id: UUID
    images: list[str] = Field(min_length=1)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    category: str | None = None


class ProductUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    images: list[str] | None = None
    characteristics: dict[str, Any] | None = None
    category: str | None = None
    is_active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str | None
    category_id: UUID | None
    images: list[str]
    characteristics: dict[str, Any]
    status: ProductStatus
    category: str | None
    is_active: bool
    skus: list[SKUResponse] = []


class PaginatedProducts(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
