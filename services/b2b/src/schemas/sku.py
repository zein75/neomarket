from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SKUImageCreate(BaseModel):
    url: str
    ordering: int = 0


class SKUImageResponse(BaseModel):
    id: UUID
    url: str
    ordering: int


class SKUCreate(BaseModel):
    product_id: UUID
    name: str
    price: int
    stock: int = 0
    images: list[SKUImageCreate] = Field(min_length=1)


class SKUUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    stock: int | None = None
    images: list[SKUImageCreate] | None = None
    is_active: bool | None = None


class SKUResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    name: str
    price: int
    discount: int = 0
    article: str | None = None
    characteristics: dict[str, Any] = Field(default_factory=dict)
    cost_price: int | None = None
    stock_quantity: int
    active_quantity: int | None = None
    reserved_quantity: int = 0
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
        data.setdefault("characteristics", {})
        data.setdefault("cost_price", None)
        if "stock_quantity" not in data and "stock" in data:
            data["stock_quantity"] = data["stock"]
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
