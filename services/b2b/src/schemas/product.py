import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.product import ProductStatus
from src.schemas.media_url import validate_media_url
from src.schemas.sku import SKUCharacteristic, SKUResponse


class ProductImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    ordering: int = 0

    @field_validator("url")
    @classmethod
    def require_public_https(cls, value: str) -> str:
        return validate_media_url(value)


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
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category_id: UUID
    brand_id: UUID | None = None
    images: list[ProductImageCreate] = Field(min_length=1)
    characteristics: list[Characteristic] = Field(default_factory=list)


class FirstSKUCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    price: int = Field(ge=0)
    stock: int = Field(default=0, ge=0)
    images: list[ProductImageCreate] = Field(min_length=1)


class ProductWithFirstSKUCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductCreate
    first_sku: FirstSKUCreate


class DraftVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_article: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    price_minor: int = Field(ge=0, le=9_223_372_036_854_775_807)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    on_hand: int = Field(ge=0, le=9_223_372_036_854_775_807)
    options: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("seller_article", "name")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProductDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=20_000)
    category_id: UUID
    brand_id: UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=100)
    media_ids: list[UUID] = Field(default_factory=list, max_length=20)
    variants: list[DraftVariantInput] = Field(min_length=1, max_length=100)

    @field_validator("title", "description")
    @classmethod
    def trim_required_product_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_variant_batch(self) -> "ProductDraftCreate":
        articles = [variant.seller_article.casefold() for variant in self.variants]
        if len(articles) != len(set(articles)):
            raise ValueError("seller_article values must be unique within the batch")
        currencies = {variant.currency for variant in self.variants}
        if len(currencies) > 1:
            raise ValueError("all variants in a product draft must use the same currency")
        return self


class ProductDraftVariantResponse(BaseModel):
    id: UUID
    seller_article: str
    name: str
    price_minor: int
    currency: str
    on_hand: int
    options: dict[str, str]


class ProductDraftResponse(BaseModel):
    id: UUID
    revision: int
    status: Literal["DRAFT"]
    operation_id: UUID
    variants: list[ProductDraftVariantResponse]


class DraftAutosaveVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    seller_article: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=255)
    price: str = Field(default="", max_length=64)
    on_hand: str = Field(default="0", max_length=64)
    options: str = Field(default="{}", max_length=20_000)


class DraftAutosavePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=20_000)
    category_id: UUID | None = None
    attributes: dict[str, str] = Field(default_factory=dict, max_length=100)
    currency: str = Field(default="RUB", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    variants: list[DraftAutosaveVariant] = Field(min_length=1, max_length=100)
    media_names: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value

    @field_validator("media_names")
    @classmethod
    def validate_media_names(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or len(item) > 255 for item in value):
            raise ValueError("media names are invalid")
        return value


class DraftAutosaveResponse(BaseModel):
    id: UUID
    revision: int
    payload: DraftAutosavePayload
    updated_at: datetime


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
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
    brand_id: UUID | None = None
    images: list[ProductImageCreate | str] | None = Field(default=None, max_length=20)
    characteristics: list[Characteristic] | None = None

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
    brand_id: UUID | None = None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    blocking_reason_id: UUID | None
    moderator_comment: str | None
    created_at: datetime
    updated_at: datetime
    revision: int = 1
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
                "brand_id": getattr(value, "brand_id", None),
                "images": getattr(value, "images", []),
                "characteristics": getattr(value, "characteristics", {}),
                "status": getattr(value, "status"),
                "blocking_reason": getattr(value, "blocking_reason", None),
                "field_reports": getattr(value, "field_reports", []),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
                "revision": getattr(value, "revision", 1),
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
        data.setdefault("revision", 1)
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
    # Canonical integer amount in minor currency units; ``price`` is retained
    # for existing B2B clients during the additive contract migration.
    price_minor: int | None = None
    currency: str = "RUB"
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
                "currency": getattr(value, "currency", "RUB"),
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
        data.setdefault("price_minor", data.get("price"))
        data.setdefault("currency", "RUB")
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
    price_minor: int | None = None
    currency: str = "RUB"
    in_stock: bool
    is_in_cart: bool
    skus: list[SKUPublicResponse] = []
    rating: float = 0.0
    reviews_count: int = 0
    category: str | None = None


class ProductPublicShortResponse(BaseModel):
    id: UUID
    seller_id: UUID
    title: str
    description: str | None
    category_id: UUID | None
    brand_id: UUID | None = None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    image: str
    price: int | None
    price_minor: int | None = None
    in_stock: bool
    is_in_cart: bool
    min_price: int | None
    min_price_minor: int | None = None
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
    field_path: str | None = None
    reason_code: str | None = None
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
    brand_id: UUID | None = None
    slug: str
    images: list[ProductImageResponse]
    characteristics: list[CharacteristicResponse]
    status: ProductStatus
    category: str | None
    is_active: bool
    deleted: bool = False
    created_at: datetime
    updated_at: datetime
    skus_count: int
    total_active_quantity: int
    skus: list[SKUResponse] | None = None


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
