from uuid import UUID

from pydantic import BaseModel, Field


class ProductShortResponse(BaseModel):
    id: UUID
    title: str
    image: str | None = None
    price: int | None = None
    price_minor: int | None = None
    in_stock: bool
    is_in_cart: bool = False


class ProductShortListResponse(BaseModel):
    items: list[ProductShortResponse]
    total_count: int
    limit: int
    offset: int


class ProductDetailSkuResponse(BaseModel):
    id: str
    name: str | None = None
    article: str | None = None
    price: int | None = None
    price_minor: int | None = None
    currency: str = "RUB"
    discount: int = 0
    available_quantity: int = 0
    in_stock: bool = False
    images: list[object] = Field(default_factory=list)


class ProductDetailResponse(BaseModel):
    """Stable public catalog detail contract consumed by storefront clients."""

    id: str
    name: str | None = None
    title: str
    description: str | None = None
    category_id: str | None = None
    category: str | None = None
    images: list[object] = Field(default_factory=list)
    characteristics: dict[str, object] = Field(default_factory=dict)
    min_price: int | None = None
    min_price_minor: int | None = None
    currency: str = "RUB"
    has_stock: bool = False
    skus: list[ProductDetailSkuResponse] = Field(default_factory=list)


class CategoryTreeItemResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None = None
    children: list["CategoryTreeItemResponse"] = Field(default_factory=list)


class CategoryTreeResponse(BaseModel):
    items: list[CategoryTreeItemResponse]


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
    created_at: str
    updated_at: str


class BreadcrumbItemResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    url: str
    level: int
    is_current: bool


class BreadcrumbsResponse(BaseModel):
    data: list[BreadcrumbItemResponse]
    meta: dict[str, str]
