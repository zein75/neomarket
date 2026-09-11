from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from src.core.config import settings


class B2CClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        service_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.b2c_url).rstrip("/")
        self.service_key = service_key or settings.service_key

    async def send_product_deleted(self, product: Any) -> None:
        event = self.build_product_deleted_event(product)
        await self._post_event(event)

    async def send_sku_out_of_stock(self, sku: Any) -> None:
        event = self.build_sku_out_of_stock_event(sku)
        await self._post_event(event)

    async def send_product_blocked(self, product: Any) -> None:
        event = self.build_product_blocked_event(product)
        await self._post_event(event)

    async def _post_event(self, event: dict[str, Any]) -> None:
        payload = {
            "event_type": event["event"],
            "idempotency_key": event["idempotency_key"],
            "occurred_at": event["date"],
            "payload": {
                "product_id": event["product_id"],
                "sku_ids": event["sku_ids"],
                "reason": event.get("reason"),
            },
        }
        async with httpx.AsyncClient(timeout=settings.b2c_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/b2b/events",
                json=payload,
                headers={"X-Service-Key": self.service_key},
            )
            if response.status_code == 409:
                return
            response.raise_for_status()

    def build_product_deleted_event(self, product: Any) -> dict[str, Any]:
        return {
            "event": "PRODUCT_DELETED",
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"b2c-product-deleted:{product.id}")),
            "date": datetime.now(timezone.utc).isoformat(),
            "product_id": str(product.id),
            "sku_ids": [str(sku.id) for sku in getattr(product, "skus", [])],
            "reason": "PRODUCT_DELETED",
        }

    def build_sku_out_of_stock_event(self, sku: Any) -> dict[str, Any]:
        return {
            "event": "SKU_OUT_OF_STOCK",
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"sku-out-of-stock:{sku.id}")),
            "date": datetime.now(timezone.utc).isoformat(),
            "product_id": str(sku.product_id),
            "sku_ids": [str(sku.id)],
        }

    def build_product_blocked_event(self, product: Any) -> dict[str, Any]:
        return {
            "event": "PRODUCT_BLOCKED",
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-blocked:{product.id}")),
            "date": datetime.now(timezone.utc).isoformat(),
            "product_id": str(product.id),
            "sku_ids": [str(sku.id) for sku in getattr(product, "skus", [])],
            "reason": str(product.status),
        }
