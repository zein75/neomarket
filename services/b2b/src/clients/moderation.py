from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from src.core.config import settings


class ModerationClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        service_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.moderation_url).rstrip("/")
        self.service_key = service_key or settings.service_key

    async def send_product_created(self, product: Any) -> None:
        event = self.build_product_created_event(product)
        await self._post_event(event)

    async def send_product_edited(
        self,
        product: Any,
        *,
        json_before: dict[str, Any],
    ) -> None:
        event = self.build_product_edited_event(product, json_before=json_before)
        await self._post_event(event)

    async def _post_event(self, event: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=settings.moderation_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/b2b/events",
                json=event,
                headers={"X-Service-Key": self.service_key},
            )
            if response.status_code == 409:
                return
            response.raise_for_status()

    def build_product_created_event(self, product: Any) -> dict[str, Any]:
        return {
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-created:{product.id}")),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product.id),
                "seller_id": str(product.seller_id),
                "category_id": str(product.category_id) if product.category_id else None,
                "queue_priority": 3,
                "json_after": self.product_snapshot(product),
            },
        }

    def build_product_edited_event(
        self,
        product: Any,
        *,
        json_before: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product.id),
                "seller_id": str(product.seller_id),
                "category_id": str(product.category_id) if product.category_id else None,
                "queue_priority": 3,
                "json_before": json_before,
                "json_after": self.product_snapshot(product),
            },
        }

    def product_snapshot(self, product: Any) -> dict[str, Any]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "images": product.images,
            "characteristics": product.characteristics,
            "status": self._status_value(product.status),
            "skus": [
                {
                    "id": str(sku.id),
                    "product_id": str(sku.product_id),
                    "name": sku.name,
                    "price": sku.price,
                    "stock": sku.stock,
                    "reserved_quantity": getattr(sku, "reserved_quantity", 0),
                    "images": sku.images,
                }
                for sku in product.skus
            ],
        }

    def _status_value(self, status: Any) -> str:
        if isinstance(status, Enum):
            return status.value
        return str(status)
