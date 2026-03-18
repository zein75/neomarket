from typing import Any

import httpx
from fastapi import HTTPException


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
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail=str(e)
            )
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
