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
        async with httpx.AsyncClient(timeout=settings.b2c_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/b2b/events",
                json=event,
                headers={"X-Service-Key": self.service_key},
            )
            if response.status_code == 409:
                return
            response.raise_for_status()

    def build_product_deleted_event(self, product: Any) -> dict[str, Any]:
        return {
            "event_type": "PRODUCT_DELETED",
            "idempotency_key": str(uuid5(NAMESPACE_URL, f"b2c-product-deleted:{product.id}")),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product.id),
                "sku_ids": [str(sku.id) for sku in product.skus],
            },
        }
