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
        sort: str = "popularity",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        self._validate_sort(sort)
        products = await self._load_products()
        filtered = [
            product
            for product in products
            if self._matches(product, category_id, price_min, price_max, in_stock, q)
        ]
        sorted_products = self._sort(filtered, sort)
        page = sorted_products[offset : offset + limit]
        return {
            "items": [self._card(product) for product in page],
            "total_count": len(filtered),
            "limit": limit,
            "offset": offset,
        }

    async def facets(self) -> dict[str, object]:
        products = await self._load_products()
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

    async def _load_products(self) -> list[dict[str, Any]]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                return await client.get_public_products()
        except HTTPException as exc:
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=502,
                    detail="B2B catalog is unavailable",
                ) from exc
            raise

    def _validate_sort(self, sort: str) -> None:
        if sort not in ALLOWED_SORTS:
            allowed = ", ".join(sorted(ALLOWED_SORTS))
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort '{sort}'. Allowed values: {allowed}",
            )

    def _matches(
        self,
        product: dict[str, Any],
        category_id: str | None,
        price_min: int | None,
        price_max: int | None,
        in_stock: bool | None,
        q: str | None,
    ) -> bool:
        min_price = self._min_price(product)
        if category_id and str(product.get("category_id")) != category_id:
            return False
        if price_min is not None and (min_price is None or min_price < price_min):
            return False
        if price_max is not None and (min_price is None or min_price > price_max):
            return False
        if in_stock is True and not self._has_stock(product):
            return False
        if q and q.lower() not in str(product.get("title", "")).lower():
            return False
        return True

    def _sort(self, products: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        if sort == "price_asc":
            return sorted(products, key=lambda product: self._min_price(product) or 0)
        if sort == "price_desc":
            return sorted(
                products,
                key=lambda product: self._min_price(product) or 0,
                reverse=True,
            )
        if sort == "new":
            return sorted(products, key=lambda product: str(product.get("id")), reverse=True)
        return products

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

    def _min_price(self, product: dict[str, Any]) -> int | None:
        prices = [
            int(sku["price"])
            for sku in product.get("skus", [])
            if int(sku.get("active_quantity", 0)) > 0 and sku.get("price") is not None
        ]
        return min(prices) if prices else None

    def _has_stock(self, product: dict[str, Any]) -> bool:
        return any(int(sku.get("active_quantity", 0)) > 0 for sku in product.get("skus", []))
