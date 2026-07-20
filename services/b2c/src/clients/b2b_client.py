from typing import Any

import httpx
from fastapi import HTTPException

from src.core.config import settings


class B2BClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def __aenter__(self) -> "B2BClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        try:
            response = await self._client.get(
                path,
                params={k: v for k, v in params.items() if v is not None},
                headers={"X-Service-Key": settings.service_key},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail=str(e)
            )
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="B2B service unavailable")

    async def _post_service(self, path: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(
                path,
                json=payload,
                headers={"X-Service-Key": settings.service_key},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            detail: Any
            try:
                detail = e.response.json().get("detail", str(e))
            except ValueError:
                detail = str(e)
            raise HTTPException(status_code=e.response.status_code, detail=detail)
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="B2B service unavailable")

    async def get_products(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
    ) -> Any:
        return await self._get("/products", page=page, page_size=page_size, search=search)

    async def get_product(self, product_id: str) -> Any:
        return await self._get(f"/products/{product_id}")

    async def get_public_products(self, *, limit: int | None = None, offset: int | None = None) -> Any:
        try:
            response = await self._client.get(
                "/api/v1/public/products",
                params={
                    k: v
                    for k, v in {"limit": limit, "offset": offset}.items()
                    if v is not None
                },
                headers={"X-Service-Key": settings.service_key},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=str(e))
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="B2B service unavailable")

    async def get_products_batch(self, product_ids: list[str]) -> Any:
        try:
            response = await self._client.post(
                "/api/v1/public/products/batch",
                json={"product_ids": product_ids},
                headers={"X-Service-Key": settings.service_key},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=str(e))
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="B2B service unavailable")

    async def get_sku(self, sku_id: str) -> Any:
        offset = 0
        limit = 100
        while True:
            payload = await self.get_public_products(limit=limit, offset=offset)
            products = payload.get("items", []) if isinstance(payload, dict) else payload
            for product in products:
                for sku in product.get("skus", []):
                    if str(sku.get("id")) == sku_id:
                        return {
                            **sku,
                            "product_id": product.get("id"),
                        }
            total_count = int(payload.get("total_count", len(products))) if isinstance(payload, dict) else len(products)
            offset += limit
            if offset >= total_count or not products:
                break
        raise HTTPException(status_code=404, detail="SKU not found")

    async def reserve(self, payload: dict[str, Any]) -> Any:
        return await self._post_service("/api/v1/reserve", payload)

    async def unreserve(self, payload: dict[str, Any]) -> Any:
        return await self._post_service("/api/v1/unreserve", payload)
