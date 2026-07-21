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
                body = e.response.json()
                detail = body.get("detail", body) if isinstance(body, dict) else body
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
        return await self._get(f"/api/v1/public/products/{product_id}")

    async def get_similar_products(
        self,
        product_id: str,
        *,
        category_id: str,
        limit: int = 8,
        offset: int = 0,
    ) -> Any:
        return await self._get(
            f"/api/v1/public/products/{product_id}/similar",
            category=category_id,
            limit=limit,
            offset=offset,
        )

    async def get_public_products(
        self,
        *,
        category_id: str | None = None,
        search: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        in_stock: bool | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Any:
        try:
            response = await self._client.get(
                "/api/v1/public/products",
                params={
                    k: v
                    for k, v in {
                        "category_id": category_id,
                        "search": search,
                        "min_price": min_price,
                        "max_price": max_price,
                        "in_stock": in_stock,
                        "sort": sort,
                        "limit": limit,
                        "offset": offset,
                    }.items()
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

    async def get_categories(self) -> Any:
        return await self._get("/api/v1/public/categories")

    async def get_category(
        self,
        category_id: str,
        *,
        include_product_count: bool = False,
    ) -> Any:
        return await self._get(
            f"/api/v1/public/categories/{category_id}",
            include_product_count=include_product_count,
        )

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
        return await self._get(f"/api/v1/public/skus/{sku_id}")

    async def reserve(self, payload: dict[str, Any]) -> Any:
        return await self._post_service("/api/v1/inventory/reserve", payload)

    async def unreserve(self, payload: dict[str, Any]) -> Any:
        return await self._post_service("/api/v1/inventory/unreserve", payload)

    async def fulfill(self, payload: dict[str, Any]) -> Any:
        return await self._post_service("/api/v1/inventory/fulfill", payload)
