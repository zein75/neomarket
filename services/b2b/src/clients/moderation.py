from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx

from src.core.config import settings
from shared.utils.service_auth import service_headers


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

    async def send_product_deleted(self, product: Any) -> None:
        event = self.build_product_deleted_event(product)
        await self._post_event(event)

    async def _post_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") in {
            "product.publication.applied.v1",
            "product.publication.rejected.v1",
        }:
            async with httpx.AsyncClient(timeout=settings.moderation_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/internal/v1/events/products",
                    json=event,
                    headers=service_headers(settings, audience="neomarket-admin", legacy_key=self.service_key),
                )
                response.raise_for_status()
            return
        event_types = {
            "PRODUCT_CREATED": "product.created",
            "PRODUCT_EDITED": "product.updated",
            "PRODUCT_DELETED": "product.deleted",
        }
        event_type = event_types.get(str(event.get("event_type")))
        payload = event.get("payload")
        if event_type is None or not isinstance(payload, dict):
            raise ValueError("Unsupported product moderation outbox event")
        product_id = UUID(str(payload.get("product_id")))
        event_id = UUID(str(event.get("idempotency_key")))
        snapshot = payload.get("json_after")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        revision = int(event.get("aggregate_version") or snapshot.get("revision") or 1)
        envelope = {
            "schema_version": 1,
            "event_id": str(event_id),
            "event_type": event_type,
            "producer": "b2b",
            "aggregate_type": "product",
            "aggregate_id": str(product_id),
            "aggregate_version": revision,
            "occurred_at": event["occurred_at"],
            "correlation_id": str(event_id),
            "payload": payload,
        }
        async with httpx.AsyncClient(timeout=settings.moderation_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/internal/v1/events/products",
                json=envelope,
                headers=service_headers(settings, audience="neomarket-admin", legacy_key=self.service_key),
            )
            response.raise_for_status()

    async def get_blocking_reason(self, reason_id: str) -> dict[str, str] | None:
        """Resolve the seller-visible reason from moderation's source of truth."""
        async with httpx.AsyncClient(timeout=settings.moderation_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/blocking-reasons",
                headers=service_headers(settings, audience="neomarket-admin", legacy_key=self.service_key),
            )
            response.raise_for_status()
        for reason in response.json():
            if str(reason.get("id")) == reason_id:
                return {
                    "id": reason_id,
                    "title": str(reason.get("title") or ""),
                    "comment": str(reason.get("description") or ""),
                }
        return None

    def build_product_created_event(self, product: Any) -> dict[str, Any]:
        return {
            "event_type": "PRODUCT_CREATED",
            "aggregate_version": int(getattr(product, "revision", 1)),
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
            "aggregate_version": int(getattr(product, "revision", 1)),
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

    def build_product_deleted_event(self, product: Any) -> dict[str, Any]:
        return {
            "event_type": "PRODUCT_DELETED",
            "aggregate_version": int(getattr(product, "revision", 1)),
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-deleted:{product.id}")),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product.id),
            },
        }

    def product_snapshot(self, product: Any) -> dict[str, Any]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "brand_id": str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None,
            "images": product.images,
            "characteristics": product.characteristics,
            "status": self._status_value(product.status),
            "revision": int(getattr(product, "revision", 1)),
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
