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
        search = self._normalize_search(q)
        payload = await self._load_products(
            category_id=category_id,
            search=search,
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

    async def category_tree(self) -> dict[str, object]:
        categories = await self._load_categories()
        self._ensure_category_hierarchy(categories)
        nodes = {
            str(category["id"]): {
                "id": category["id"],
                "name": category["name"],
                "parent_id": category.get("parent_id"),
                "children": [],
            }
            for category in categories
        }
        roots: list[dict[str, object]] = []
        for category in categories:
            node = nodes[str(category["id"])]
            parent_id = category.get("parent_id")
            if parent_id is None:
                roots.append(node)
            else:
                nodes[str(parent_id)]["children"].append(node)
        return {"items": roots}

    async def category_detail(
        self,
        category_id: str,
        *,
        include_product_count: bool = False,
    ) -> dict[str, object]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                return await client.get_category(
                    category_id,
                    include_product_count=include_product_count,
                )
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": "Category not found"},
                ) from exc
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise

    async def breadcrumbs(
        self,
        *,
        category_id: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, object]:
        if category_id and product_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "ambiguous_param",
                    "message": "only one of category_id or product_id must be provided",
                },
            )
        if not category_id and not product_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "missing_param",
                    "message": "category_id or product_id must be provided",
                },
            )
        resolved_via = "category_id" if category_id else "product_id"
        resolved_category_id = category_id
        if product_id:
            product = await self.get_product_card(product_id)
            resolved_category_id = str(product.get("category_id") or "")
            if not resolved_category_id:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": "Category not found"},
                )
        categories = await self._load_categories()
        path = self._category_path(categories, str(resolved_category_id))
        slugs: list[str] = []
        data: list[dict[str, object]] = []
        for level, category in enumerate(path):
            slugs.append(str(category["slug"]))
            data.append(
                {
                    "id": category["id"],
                    "slug": category["slug"],
                    "name": category["name"],
                    "url": "/catalog/" + "/".join(slugs),
                    "level": level,
                    "is_current": level == len(path) - 1,
                }
            )
        meta = {
            "resolved_via": resolved_via,
            "category_id": str(resolved_category_id),
        }
        if product_id:
            meta["product_id"] = product_id
        return {"data": data, "meta": meta}

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
                    status_code=503,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise
        return self._detail(product)

    async def similar_products(
        self,
        product_id: str,
        *,
        category_id: str,
        limit: int = 8,
        offset: int = 0,
    ) -> dict[str, object]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                payload = await client.get_similar_products(
                    product_id,
                    category_id=category_id,
                    limit=limit,
                    offset=offset,
                )
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "NOT_FOUND",
                        "message": "Product not found",
                    },
                ) from exc
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise
        products, total_count, response_limit, response_offset = self._catalog_page(
            payload,
            fallback_limit=limit,
            fallback_offset=offset,
        )
        return {
            "items": [self._short_card(product) for product in products],
            "total_count": total_count,
            "limit": response_limit,
            "offset": response_offset,
        }

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

    async def _load_categories(self) -> list[dict[str, Any]]:
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                payload = await client.get_categories()
        except HTTPException as exc:
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "B2B catalog is unavailable",
                    },
                ) from exc
            raise
        if isinstance(payload, dict):
            return list(payload.get("items", []))
        return list(payload)

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

    def _ensure_category_hierarchy(self, categories: list[dict[str, Any]]) -> None:
        ids = {str(category["id"]) for category in categories}
        for category in categories:
            parent_id = category.get("parent_id")
            if parent_id is not None and str(parent_id) not in ids:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "orphan_node",
                        "message": "category hierarchy is broken",
                    },
                )

    def _category_path(
        self,
        categories: list[dict[str, Any]],
        category_id: str,
    ) -> list[dict[str, Any]]:
        self._ensure_category_hierarchy(categories)
        by_id = {str(category["id"]): category for category in categories}
        current = by_id.get(category_id)
        if current is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Category not found"},
            )
        path = [current]
        seen = {category_id}
        while current.get("parent_id") is not None:
            parent_id = str(current["parent_id"])
            if parent_id in seen:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "orphan_node",
                        "message": "category hierarchy is broken",
                    },
                )
            parent = by_id.get(parent_id)
            if parent is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "orphan_node",
                        "message": "category hierarchy is broken",
                    },
                )
            path.append(parent)
            seen.add(parent_id)
            current = parent
        return list(reversed(path))

    def _validate_sort(self, sort: str) -> None:
        if sort not in ALLOWED_SORTS:
            allowed = ", ".join(sorted(ALLOWED_SORTS))
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort '{sort}'. Allowed values: {allowed}",
            )

    def _normalize_search(self, search: str | None) -> str | None:
        if search is None:
            return None
        normalized = search.strip()
        if len(normalized) < 3:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Search query must contain at least 3 characters",
                },
            )
        return normalized

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

    def _short_card(self, product: dict[str, Any]) -> dict[str, object]:
        images = product.get("images") or []
        first_image = images[0] if images else None
        image_url = first_image.get("url") if isinstance(first_image, dict) else first_image
        price = product.get("min_price")
        if price is None:
            price = self._min_price(product)
        return {
            "id": product.get("id"),
            "title": product.get("title") or product.get("name"),
            "image": image_url,
            "price": price,
            "in_stock": bool(product.get("has_stock", price is not None)),
            "is_in_cart": False,
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
