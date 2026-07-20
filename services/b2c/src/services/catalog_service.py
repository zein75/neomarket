from collections import Counter
from typing import Any

from fastapi import HTTPException

from src.clients.b2b_client import B2BClient
from src.core.config import settings


ALLOWED_SORTS = {"price_asc", "price_desc", "popularity", "new"}


class CatalogService:
    async def list_products(
        self,
        *,
        category_id: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        in_stock: bool | None = None,
        q: str | None = None,
        seller_id: str | None = None,
        sort: str = "popularity",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        self._validate_sort(sort)
        payload = await self._load_products(
            category_id=category_id,
            search=q,
            min_price=price_min,
            max_price=price_max,
            in_stock=in_stock,
            seller_id=seller_id,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        products, total_count, response_limit, response_offset = self._catalog_page(
            payload,
            fallback_limit=limit,
            fallback_offset=offset,
        )
        return {
            "items": [self._card(product) for product in products],
            "total_count": total_count,
            "limit": response_limit,
            "offset": response_offset,
        }

    async def facets(self) -> dict[str, object]:
        products = await self._load_all_products()
        category_counts: Counter[tuple[str, str]] = Counter()
        prices: list[int] = []
        in_stock_count = 0
        for product in products:
            category_id = str(product.get("category_id") or "")
            category_name = str(product.get("category") or category_id)
            if category_id:
                category_counts[(category_id, category_name)] += 1
            min_price = self._min_price(product)
            if min_price is not None:
                prices.append(min_price)
            if self._has_stock(product):
                in_stock_count += 1

        categories = [
            {"id": category_id, "name": name, "count": count}
            for (category_id, name), count in sorted(category_counts.items())
        ]
        return {
            "categories": categories,
            "price": {
                "min": min(prices) if prices else None,
                "max": max(prices) if prices else None,
            },
            "in_stock": {"true": in_stock_count},
        }

    async def get_product_card(self, product_id: str) -> dict[str, object]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                product = await client.get_product(product_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "PRODUCT_NOT_FOUND",
                        "message": "Product not found",
                    },
                ) from exc
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise
        return self._detail(product)

    async def _load_all_products(self) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        limit = 100
        offset = 0

        while True:
            payload = await self._load_products(limit=limit, offset=offset)
            items, total_count, response_limit, response_offset = self._catalog_page(
                payload,
                fallback_limit=limit,
                fallback_offset=offset,
            )
            products.extend(items)
            next_offset = response_offset + response_limit
            if not items or next_offset >= total_count:
                return products
            offset = next_offset

    async def _load_products(self, **params: Any) -> list[dict[str, Any]] | dict[str, Any]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                return await client.get_public_products(**params)
        except HTTPException as exc:
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise

    def _catalog_page(
        self,
        payload: list[dict[str, Any]] | dict[str, Any],
        *,
        fallback_limit: int,
        fallback_offset: int,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        if not isinstance(payload, dict):
            return payload, len(payload), fallback_limit, fallback_offset

        items = list(payload.get("items", []))
        return (
            items,
            int(payload.get("total_count", len(items))),
            int(payload.get("limit", fallback_limit)),
            int(payload.get("offset", fallback_offset)),
        )

    def _validate_sort(self, sort: str) -> None:
        if sort not in ALLOWED_SORTS:
            allowed = ", ".join(sorted(ALLOWED_SORTS))
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort '{sort}'. Allowed values: {allowed}",
            )

    def _card(self, product: dict[str, Any]) -> dict[str, object]:
        return {
            "id": product.get("id"),
            "name": product.get("title"),
            "description": product.get("description"),
            "category_id": product.get("category_id"),
            "category": product.get("category"),
            "min_price": self._min_price(product),
            "has_stock": self._has_stock(product),
            "images": product.get("images") or [],
            "skus": product.get("skus") or [],
        }

    def _detail(self, product: dict[str, Any]) -> dict[str, object]:
        return {
            "id": product.get("id"),
            "name": product.get("title"),
            "title": product.get("title"),
            "description": product.get("description"),
            "category_id": product.get("category_id"),
            "category": product.get("category"),
            "images": product.get("images") or [],
            "characteristics": product.get("characteristics") or {},
            "min_price": self._min_price(product),
            "has_stock": self._has_stock(product),
            "skus": [self._public_sku(sku) for sku in product.get("skus", [])],
        }

    def _public_sku(self, sku: dict[str, Any]) -> dict[str, object]:
        active_quantity = int(sku.get("active_quantity", 0))
        return {
            "id": sku.get("id"),
            "name": sku.get("name"),
            "price": sku.get("price"),
            "discount": int(sku.get("discount", 0) or 0),
            "available_quantity": active_quantity,
            "in_stock": active_quantity > 0,
            "images": sku.get("images") or [],
        }

    def _min_price(self, product: dict[str, Any]) -> int | None:
        prices = [
            int(sku["price"])
            for sku in product.get("skus", [])
            if int(sku.get("active_quantity", 0)) > 0 and sku.get("price") is not None
        ]
        return min(prices) if prices else None

    def _has_stock(self, product: dict[str, Any]) -> bool:
        return any(int(sku.get("active_quantity", 0)) > 0 for sku in product.get("skus", []))
