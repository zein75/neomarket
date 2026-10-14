import re
import ipaddress
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.product import ProductStatus
from src.schemas.sku import SKUCharacteristic, SKUResponse


class ProductImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    ordering: int = 0

    @field_validator("url")
    @classmethod
    def require_public_https(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("image URL must use https")
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("image URL host is not public")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private or address.is_loopback or address.is_link_local
        ):
            raise ValueError("image URL host is not public")
        return value


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
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    images: list[ProductImageCreate] | None = None
    characteristics: list[Characteristic] | None = None
    category: str | None = None
    is_active: bool | None = None


class ProductPatch(BaseModel):
    """Strict canonical PATCH body from the B2B HTTP contract."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    category_id: UUID | None = None
    images: list[ProductImageCreate | str] | None = Field(default=None, max_length=20)

    @field_validator("images", mode="before")
    @classmethod
    def normalize_image_urls(cls, value: Any) -> Any:
        if value is None:
            return value
        return [({"url": image} if isinstance(image, str) else image) for image in value]

    @model_validator(mode="after")
    def require_change(self) -> "ProductPatch":
        if not self.model_fields_set:
            raise ValueError("at least one product field is required")
        return self


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
    deleted: bool
    skus: list[SKUResponse]

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
        data.setdefault("deleted", False)
        data.setdefault("skus", [])
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


class SKUPublicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    name: str
    price: int
    discount: int
    article: str | None
    characteristics: list[SKUCharacteristic]
    stock_quantity: int
    active_quantity: int
    images: list[dict[str, Any]]
    is_active: bool

    @model_validator(mode="before")
    @classmethod
    def from_sku_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            stock = getattr(value, "stock")
            on_hand = getattr(value, "on_hand", None)
            reserved = getattr(value, "reserved_quantity", 0)
            data = {
                "id": getattr(value, "id"),
                "product_id": getattr(value, "product_id"),
                "name": getattr(value, "name"),
                "price": getattr(value, "price"),
                "stock_quantity": getattr(value, "stock"),
                "active_quantity": max(
                    (stock if on_hand is None else on_hand) - reserved,
                    0,
                ),
                "images": getattr(value, "images", []),
                "is_active": getattr(value, "is_active"),
            }
            for optional in ("discount", "article", "characteristics"):
                if hasattr(value, optional):
                    data[optional] = getattr(value, optional)
        data.setdefault("discount", 0)
        data.setdefault("article", None)
        if "stock_quantity" not in data and "stock" in data:
            data["stock_quantity"] = data["stock"]
        data["characteristics"] = SKUResponse._normalize_characteristics(
            data.get("characteristics", [])
        )
        if data.get("active_quantity") is None:
            data["active_quantity"] = data["stock_quantity"]
        data["images"] = SKUResponse._normalize_images(
            data.get("images", []), data.get("id")
        )
        return data


class ProductPublicResponse(ProductResponse):
    image: str
    price: int | None
    in_stock: bool
    is_in_cart: bool
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
    image: str
    price: int | None
    in_stock: bool
    is_in_cart: bool
    min_price: int | None
    created_at: datetime


class ProductPublicPaginatedResponse(BaseModel):
    items: list[ProductPublicResponse]
    total_count: int
    limit: int
    offset: int


class ProductPublicBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID] = Field(min_length=1, max_length=100)


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
    blocking_reason: BlockingReasonResponse | None
    field_reports: list[FieldReportResponse]


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
