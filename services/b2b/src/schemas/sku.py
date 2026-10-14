from datetime import datetime, timezone
import ipaddress
from urllib.parse import urlparse
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SKUImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    ordering: int = 0

    @field_validator("url")
    @classmethod
    def require_https_url(cls, value: str) -> str:
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


class SKUImageResponse(BaseModel):
    id: UUID
    url: str
    ordering: int


class SKUCharacteristic(BaseModel):
    name: str
    value: str


class SKUCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    name: str
    price: int = Field(ge=0)
    discount: int = Field(default=0, ge=0)
    cost_price: int | None = None
    article: str | None = None
    stock: int = Field(default=0, ge=0)
    images: list[SKUImageCreate] = Field(min_length=1)
    characteristics: list[SKUCharacteristic] = Field(default_factory=list)


class SKUUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    price: int | None = Field(default=None, ge=0)
    discount: int | None = Field(default=None, ge=0)
    cost_price: int | None = None
    article: str | None = None
    characteristics: list[SKUCharacteristic] | None = None
    stock: int | None = Field(default=None, ge=0)
    images: list[SKUImageCreate] | None = None
    is_active: bool | None = None


class SKUPatch(BaseModel):
    """Strict canonical seller SKU patch; maps contract names to domain fields."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    on_hand: int | None = Field(default=None, ge=0)
    images: list[SKUImageCreate | str] | None = Field(default=None, max_length=20)
    is_active: bool | None = None

    @field_validator("images", mode="before")
    @classmethod
    def normalize_image_urls(cls, value: Any) -> Any:
        if value is None:
            return value
        return [({"url": image} if isinstance(image, str) else image) for image in value]

    @model_validator(mode="after")
    def normalize_contract_fields(self) -> "SKUPatch":
        if not self.model_fields_set:
            raise ValueError("at least one SKU field is required")
        return self


class StockAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def require_nonzero_delta(self) -> "StockAdjustmentRequest":
        if self.delta == 0:
            raise ValueError("delta must not be zero")
        return self


class SKUResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    name: str
    price: int
    discount: int
    article: str | None
    characteristics: list[SKUCharacteristic]
    cost_price: int | None
    stock_quantity: int
    active_quantity: int
    reserved_quantity: int
    images: list[SKUImageResponse]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_sku_model(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": getattr(value, "id"),
                "product_id": getattr(value, "product_id"),
                "name": getattr(value, "name"),
                "price": getattr(value, "price"),
                "stock_quantity": getattr(value, "stock"),
                "active_quantity": getattr(value, "active_quantity", None),
                "reserved_quantity": getattr(value, "reserved_quantity", 0),
                "images": getattr(value, "images", []),
                "is_active": getattr(value, "is_active"),
                "created_at": getattr(value, "created_at"),
                "updated_at": getattr(value, "updated_at"),
            }
            for optional in ("discount", "article", "characteristics", "cost_price"):
                if hasattr(value, optional):
                    data[optional] = getattr(value, optional)

        data.setdefault("discount", 0)
        data.setdefault("article", None)
        data["characteristics"] = cls._normalize_characteristics(
            data.get("characteristics", [])
        )
        data.setdefault("cost_price", None)
        data.setdefault("reserved_quantity", 0)
        now = datetime.now(timezone.utc)
        if data.get("created_at") is None:
            data["created_at"] = now
        if data.get("updated_at") is None:
            data["updated_at"] = now
        if "stock_quantity" not in data and "stock" in data:
            data["stock_quantity"] = data["stock"]
        if data.get("active_quantity") is None:
            on_hand = getattr(value, "on_hand", None)
            data["active_quantity"] = max(
                (data["stock_quantity"] if on_hand is None else on_hand)
                - data.get("reserved_quantity", 0),
                0,
            )
        data["images"] = cls._normalize_images(data.get("images", []), data.get("id"))
        return data

    @classmethod
    def _normalize_images(cls, images: list[Any], sku_id: Any) -> list[dict[str, Any]]:
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
                    or uuid5(NAMESPACE_URL, f"sku-image:{sku_id}:{ordering}:{url}"),
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
