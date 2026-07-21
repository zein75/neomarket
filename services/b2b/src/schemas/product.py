import re
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.product import ProductStatus
from src.schemas.sku import SKUResponse


class ProductImageCreate(BaseModel):
    url: str
    ordering: int = 0


class ProductImageResponse(BaseModel):
    id: UUID
    url: str
    ordering: int


class Characteristic(BaseModel):
    name: str
    value: str


class CharacteristicResponse(Characteristic):
    pass


class ProductCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category_id: UUID
    images: list[ProductImageCreate] = Field(min_length=1)
    characteristics: list[Characteristic] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    images: list[ProductImageCreate] | None = None
    characteristics: list[Characteristic] | None = None
    category: str | None = None
    is_active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str | None
    category_id: UUID | None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    blocking_reason_id: UUID | None
    moderator_comment: str | None
    created_at: datetime
    updated_at: datetime
    deleted: bool = False
    skus: list[SKUResponse] = []

    @model_validator(mode="before")
    @classmethod
    def from_product_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": getattr(value, "id"),
                "seller_id": getattr(value, "seller_id"),
                "title": getattr(value, "title"),
                "slug": getattr(value, "slug", None),
                "description": getattr(value, "description"),
                "category_id": getattr(value, "category_id", None),
                "images": getattr(value, "images", []),
                "characteristics": getattr(value, "characteristics", {}),
                "status": getattr(value, "status"),
                "blocking_reason": getattr(value, "blocking_reason", None),
                "field_reports": getattr(value, "field_reports", []),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
                "deleted": getattr(value, "deleted", False),
                "skus": getattr(value, "skus", []),
            }

        now = datetime.now(timezone.utc)
        if data.get("created_at") is None:
            data["created_at"] = now
        if data.get("updated_at") is None:
            data["updated_at"] = now
        if not data.get("slug"):
            data["slug"] = cls._slug(data["title"], data["id"])
        data.setdefault("blocking_reason_id", cls._blocking_reason_id(data))
        data.setdefault("moderator_comment", cls._moderator_comment(data))
        data["images"] = cls._normalize_images(data.get("images", []), data.get("id"))
        data["characteristics"] = cls._normalize_characteristics(
            data.get("characteristics", [])
        )
        return data

    @classmethod
    def _normalize_images(
        cls, images: list[Any], product_id: Any
    ) -> list[dict[str, Any]]:
        normalized = []
        for index, image in enumerate(images):
            if isinstance(image, dict):
                url = image["url"]
                ordering = image.get("ordering", index)
                image_id = image.get("id")
            elif hasattr(image, "url"):
                url = image.url
                ordering = getattr(image, "ordering", index)
                image_id = getattr(image, "id", None)
            else:
                url = str(image)
                ordering = index
                image_id = None
            normalized.append(
                {
                    "id": image_id
                    or uuid5(NAMESPACE_URL, f"product-image:{product_id}:{ordering}:{url}"),
                    "url": url,
                    "ordering": ordering,
                }
            )
        return normalized

    @classmethod
    def _normalize_characteristics(cls, characteristics: Any) -> list[dict[str, str]]:
        if isinstance(characteristics, dict):
            return [
                {"name": str(name), "value": str(value)}
                for name, value in characteristics.items()
            ]
        return [
            {
                "name": str(item["name"] if isinstance(item, dict) else item.name),
                "value": str(item["value"] if isinstance(item, dict) else item.value),
            }
            for item in characteristics
        ]

    @classmethod
    def _slug(cls, title: str, product_id: Any) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return f"{slug or 'product'}-{str(product_id)[:8]}"

    @classmethod
    def _blocking_reason_id(cls, data: dict[str, Any]) -> UUID | None:
        reason = data.get("blocking_reason")
        if isinstance(reason, dict) and reason.get("id"):
            return UUID(str(reason["id"]))
        return data.get("blocking_reason_id")

    @classmethod
    def _moderator_comment(cls, data: dict[str, Any]) -> str | None:
        if data.get("moderator_comment") is not None:
            return str(data["moderator_comment"])
        reason = data.get("blocking_reason")
        if isinstance(reason, dict) and reason.get("comment") is not None:
            return str(reason["comment"])
        field_reports = data.get("field_reports") or []
        if field_reports:
            report = field_reports[0]
            if isinstance(report, dict) and report.get("comment") is not None:
                return str(report["comment"])
        return None


class ProductCreateResponse(ProductResponse):
    blocked: bool = False

    @model_validator(mode="before")
    @classmethod
    def from_product_model(cls, value: Any) -> Any:
        data = super().from_product_model(value)
        status_value = data.get("status")
        data["blocked"] = status_value in {
            ProductStatus.BLOCKED,
            ProductStatus.HARD_BLOCKED,
            ProductStatus.BLOCKED.value,
            ProductStatus.HARD_BLOCKED.value,
        }
        return data


class SKUPublicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    name: str
    price: int
    discount: int = 0
    article: str | None = None
    characteristics: dict[str, Any] = Field(default_factory=dict)
    stock_quantity: int
    active_quantity: int | None = None
    images: list[dict[str, Any]]
    is_active: bool

    @model_validator(mode="before")
    @classmethod
    def from_sku_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            stock = getattr(value, "stock")
            reserved = getattr(value, "reserved_quantity", 0)
            data = {
                "id": getattr(value, "id"),
                "product_id": getattr(value, "product_id"),
                "name": getattr(value, "name"),
                "price": getattr(value, "price"),
                "stock_quantity": getattr(value, "stock"),
                "active_quantity": max(stock - reserved, 0),
                "images": getattr(value, "images", []),
                "is_active": getattr(value, "is_active"),
            }
            for optional in ("discount", "article", "characteristics"):
                if hasattr(value, optional):
                    data[optional] = getattr(value, optional)
        data.setdefault("discount", 0)
        data.setdefault("article", None)
        data.setdefault("characteristics", {})
        if "stock_quantity" not in data and "stock" in data:
            data["stock_quantity"] = data["stock"]
        data["images"] = SKUResponse._normalize_images(
            data.get("images", []), data.get("id")
        )
        return data


class ProductPublicResponse(ProductResponse):
    skus: list[SKUPublicResponse] = []


class ProductPublicShortResponse(BaseModel):
    id: UUID
    seller_id: UUID
    title: str
    description: str | None
    category_id: UUID | None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    min_price: int | None
    created_at: datetime


class ProductPublicPaginatedResponse(BaseModel):
    items: list[ProductPublicShortResponse]
    total_count: int
    limit: int
    offset: int


class ProductPublicBatchRequest(BaseModel):
    product_ids: list[UUID] = Field(min_length=1)


class BlockingReasonResponse(BaseModel):
    id: UUID
    title: str
    comment: str


class FieldReportResponse(BaseModel):
    field_name: str
    sku_id: UUID | None = None
    comment: str


class ProductDetailResponse(ProductResponse):
    blocked: bool
    blocking_reason: BlockingReasonResponse | None = None
    field_reports: list[FieldReportResponse] = []


class ProductListItem(BaseModel):
    id: UUID
    seller_id: UUID
    title: str
    description: str | None
    category_id: UUID | None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    category: str | None
    is_active: bool
    deleted: bool = False
    created_at: datetime
    skus_count: int
    total_active_quantity: int


class ProductPaginatedResponse(BaseModel):
    items: list[ProductListItem]
    total_count: int
    limit: int
    offset: int


class PaginatedProducts(BaseModel):
    items: list[ProductPublicResponse]
    total: int
    page: int
    page_size: int
