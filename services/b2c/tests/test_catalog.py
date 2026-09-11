import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.clients import b2b_client as b2b_client_module
from src.clients.b2b_client import B2BClient
from src.main import app
from src.services import catalog_service as catalog_service_module
from src.services.catalog_service import CatalogService


def _product(
    product_id: str,
    *,
    title: str,
    description: str | None = None,
    category_id: str,
    category: str,
    price: int,
    seller_id: str = "seller-1",
    active_quantity: int = 5,
) -> dict[str, object]:
    return {
        "id": product_id,
        "seller_id": seller_id,
        "title": title,
        "description": description or f"{title} description",
        "category_id": category_id,
        "category": category,
        "images": [{"url": f"https://cdn.test/{product_id}.jpg"}],
        "characteristics": {"brand": "Neo", "color": "black"},
        "skus": [
            {
                "id": f"sku-{product_id}",
                "name": "Default",
                "price": price,
                "active_quantity": active_quantity,
                "images": [],
            }
        ],
    }


def _category(
    category_id: str,
    *,
    name: str,
    slug: str,
    parent_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": category_id,
        "name": name,
        "slug": slug,
        "parent_id": parent_id,
        "is_active": True,
        "created_at": "2026-04-16T10:30:00Z",
        "updated_at": "2026-04-16T10:30:00Z",
    }


class FakeB2BClient:
    products: list[dict[str, object]] = []
    categories: list[dict[str, object]] = []
    unavailable = False
    get_public_products_calls = 0
    last_public_products_kwargs: dict[str, object] = {}
    get_product_calls: list[str] = []
    get_similar_products_calls: list[tuple[str, str, int, int]] = []

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_public_products(self, **kwargs):
        self.__class__.get_public_products_calls += 1
        self.__class__.last_public_products_kwargs = {
            key: value for key, value in kwargs.items() if value is not None
        }
        if self.unavailable:
            raise HTTPException(status_code=503, detail="B2B service unavailable")
        products = self._filtered_products(kwargs)
        limit = int(kwargs.get("limit") or len(products) or 20)
        offset = int(kwargs.get("offset") or 0)
        return {
            "items": products[offset : offset + limit],
            "total_count": len(products),
            "limit": limit,
            "offset": offset,
        }

    def _filtered_products(
        self,
        kwargs: dict[str, object],
    ) -> list[dict[str, object]]:
        products = list(self.products)
        category_id = kwargs.get("category_id")
        search = kwargs.get("search")
        min_price = kwargs.get("min_price")
        max_price = kwargs.get("max_price")
        seller_id = kwargs.get("seller_id")
        in_stock = kwargs.get("in_stock")
        sort = kwargs.get("sort")

        if category_id:
            products = [
                product
                for product in products
                if str(product.get("category_id")) == str(category_id)
            ]
        if seller_id:
            products = [
                product
                for product in products
                if str(product.get("seller_id")) == str(seller_id)
            ]
        if search:
            products = [
                product
                for product in products
                if str(search).lower()
                in " ".join(
                    str(product.get(field, "")) for field in ("title", "description")
                ).lower()
            ]
        if min_price is not None:
            products = [
                product
                for product in products
                if self._min_price(product) is not None
                and self._min_price(product) >= int(min_price)
            ]
        if max_price is not None:
            products = [
                product
                for product in products
                if self._min_price(product) is not None
                and self._min_price(product) <= int(max_price)
            ]
        if in_stock is True:
            products = [
                product
                for product in products
                if any(
                    int(sku.get("active_quantity", 0)) > 0
                    for sku in product.get("skus", [])
                )
            ]
        if sort == "price_asc":
            products = sorted(products, key=lambda product: self._min_price(product) or 0)
        elif sort == "price_desc":
            products = sorted(
                products,
                key=lambda product: self._min_price(product) or 0,
                reverse=True,
            )
        return products

    def _min_price(self, product: dict[str, object]) -> int | None:
        prices = [
            int(sku["price"])
            for sku in product.get("skus", [])
            if int(sku.get("active_quantity", 0)) > 0 and sku.get("price") is not None
        ]
        return min(prices) if prices else None

    async def get_product(self, product_id: str):
        self.__class__.get_product_calls.append(product_id)
        if self.unavailable:
            raise HTTPException(status_code=503, detail="B2B service unavailable")
        for product in self.products:
            if product["id"] == product_id:
                return product
        raise HTTPException(status_code=404, detail="Product not found")

    async def get_similar_products(
        self,
        product_id: str,
        *,
        category_id: str,
        limit: int = 8,
        offset: int = 0,
    ):
        self.__class__.get_similar_products_calls.append(
            (product_id, category_id, limit, offset)
        )
        if self.unavailable:
            raise HTTPException(status_code=503, detail="B2B service unavailable")
        current = next(
            (product for product in self.products if product["id"] == product_id),
            None,
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Product not found")
        current_category = current.get("category_id")
        products = [
            product
            for product in self.products
            if product["id"] != product_id
            and product.get("category_id") == category_id
            and product.get("category_id") == current_category
        ]
        return {
            "items": products[offset : offset + limit],
            "total_count": len(products),
            "limit": limit,
            "offset": offset,
        }

    async def get_categories(self):
        if self.unavailable:
            raise HTTPException(status_code=503, detail="B2B service unavailable")
        return {"items": list(self.categories)}

    async def get_category(
        self,
        category_id: str,
        *,
        include_product_count: bool = False,
    ):
        if self.unavailable:
            raise HTTPException(status_code=503, detail="B2B service unavailable")
        category = next(
            (category for category in self.categories if category["id"] == category_id),
            None,
        )
        if category is None:
            raise HTTPException(status_code=404, detail="Category not found")
        parent = next(
            (
                item
                for item in self.categories
                if item["id"] == category.get("parent_id")
            ),
            None,
        )
        product_count = None
        if include_product_count:
            product_count = sum(
                1 for product in self.products if product.get("category_id") == category_id
            )
        return {
            "id": category["id"],
            "name": category["name"],
            "slug": category["slug"],
            "description": category.get("description"),
            "parent": (
                {"id": parent["id"], "name": parent["name"], "slug": parent["slug"]}
                if parent
                else None
            ),
            "product_count": product_count,
            "seo": category.get("seo") or {},
            "meta_tags": category.get("meta_tags") or {},
            "image_url": category.get("image_url"),
            "is_active": category.get("is_active", True),
            "created_at": category.get("created_at", "2026-04-16T10:30:00Z"),
            "updated_at": category.get("updated_at", "2026-04-16T10:30:00Z"),
        }


@pytest.fixture(autouse=True)
def patch_b2b(monkeypatch: pytest.MonkeyPatch):
    FakeB2BClient.products = []
    FakeB2BClient.categories = []
    FakeB2BClient.unavailable = False
    FakeB2BClient.get_public_products_calls = 0
    FakeB2BClient.last_public_products_kwargs = {}
    FakeB2BClient.get_product_calls = []
    FakeB2BClient.get_similar_products_calls = []
    monkeypatch.setattr(catalog_service_module, "B2BClient", FakeB2BClient)


@pytest.mark.asyncio
async def test_catalog_returns_filtered_sorted_products() -> None:
    FakeB2BClient.products = [
        _product("p1", title="Budget keyboard", category_id="keyboards", category="Keyboards", price=5000),
        _product("p2", title="Premium keyboard", category_id="keyboards", category="Keyboards", price=15000),
        _product("p3", title="Mouse", category_id="mice", category="Mice", price=7000),
    ]

    response = await CatalogService().list_products(
        category_id="keyboards",
        price_min=4000,
        price_max=20000,
        in_stock=True,
        q="keyboard",
        sort="price_desc",
        limit=1,
        offset=0,
    )

    assert FakeB2BClient.last_public_products_kwargs == {
        "category_id": "keyboards",
        "search": "keyboard",
        "min_price": 4000,
        "max_price": 20000,
        "in_stock": True,
        "sort": "price_desc",
        "limit": 1,
        "offset": 0,
    }
    assert response["total_count"] == 2
    assert response["limit"] == 1
    assert response["offset"] == 0
    assert [item["id"] for item in response["items"]] == ["p2"]
    assert response["items"][0]["min_price"] == 15000


@pytest.mark.asyncio
async def test_search_returns_matching_products() -> None:
    FakeB2BClient.products = [
        _product(
            "p1",
            title="Wireless keyboard",
            description="Quiet office keys",
            category_id="accessories",
            category="Accessories",
            price=5000,
        ),
        _product(
            "p2",
            title="Travel mug",
            description="Keeps кофе hot",
            category_id="kitchen",
            category="Kitchen",
            price=1200,
        ),
        _product(
            "p3",
            title="Desk lamp",
            description="Warm light",
            category_id="lighting",
            category="Lighting",
            price=3000,
        ),
    ]

    by_title = await CatalogService().list_products(q="keyboard")
    by_description = await CatalogService().list_products(q="кофе")

    assert [item["id"] for item in by_title["items"]] == ["p1"]
    assert [item["id"] for item in by_description["items"]] == ["p2"]
    assert FakeB2BClient.last_public_products_kwargs["search"] == "кофе"


def test_short_query_returns_400() -> None:
    response = TestClient(app).get("/api/v1/products", params={"search": "ip"})

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Search query must contain at least 3 characters",
    }
    assert FakeB2BClient.get_public_products_calls == 0


def test_special_chars_do_not_break_query() -> None:
    FakeB2BClient.products = [
        _product(
            "p1",
            title="iPhone%15 case",
            description="Fits phone",
            category_id="cases",
            category="Cases",
            price=2500,
        ),
        _product(
            "p2",
            title="Coffee press",
            description="кофе' accessory",
            category_id="kitchen",
            category="Kitchen",
            price=1800,
        ),
    ]

    percent_response = TestClient(app).get(
        "/api/v1/products",
        params={"search": "iPhone%15"},
    )
    quote_response = TestClient(app).get(
        "/api/v1/products",
        params={"search": "кофе'"},
    )

    assert percent_response.status_code == 200
    assert [item["id"] for item in percent_response.json()["items"]] == ["p1"]
    assert quote_response.status_code == 200
    assert [item["id"] for item in quote_response.json()["items"]] == ["p2"]


def test_empty_results_returns_200() -> None:
    FakeB2BClient.products = [
        _product(
            "p1",
            title="Wireless keyboard",
            category_id="accessories",
            category="Accessories",
            price=5000,
        )
    ]

    response = TestClient(app).get("/api/v1/products", params={"search": "camera"})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total_count"] == 0


@pytest.mark.asyncio
async def test_facets_return_counts_per_filter_value() -> None:
    FakeB2BClient.products = [
        _product("p1", title="Keyboard A", category_id="keyboards", category="Keyboards", price=5000),
        _product("p2", title="Keyboard B", category_id="keyboards", category="Keyboards", price=15000),
        _product("p3", title="Mouse", category_id="mice", category="Mice", price=7000),
    ]

    response = await CatalogService().facets()

    assert response["categories"] == [
        {"id": "keyboards", "name": "Keyboards", "count": 2},
        {"id": "mice", "name": "Mice", "count": 1},
    ]
    assert response["price"]["min"] == 5000
    assert response["price"]["max"] == 15000
    assert response["in_stock"]["true"] == 3


@pytest.mark.asyncio
async def test_invalid_sort_returns_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await CatalogService().list_products(sort="rating_desc")

    assert exc_info.value.status_code == 400
    assert "price_asc" in exc_info.value.detail


@pytest.mark.asyncio
async def test_b2b_unavailable_returns_502() -> None:
    FakeB2BClient.unavailable = True

    with pytest.raises(HTTPException) as exc_info:
        await CatalogService().list_products()

    assert exc_info.value.status_code == 502


def test_category_tree_returns_nested_structure() -> None:
    root_id = "10000000-0000-0000-0000-000000000001"
    child_id = "10000000-0000-0000-0000-000000000002"
    leaf_id = "10000000-0000-0000-0000-000000000003"
    FakeB2BClient.categories = [
        _category(root_id, name="Electronics", slug="electronics"),
        _category(child_id, name="Phones", slug="phones", parent_id=root_id),
        _category(leaf_id, name="Android", slug="android", parent_id=child_id),
    ]

    response = TestClient(app).get("/api/v1/categories")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": root_id,
                "name": "Electronics",
                "parent_id": None,
                "children": [
                    {
                        "id": child_id,
                        "name": "Phones",
                        "parent_id": root_id,
                        "children": [
                            {
                                "id": leaf_id,
                                "name": "Android",
                                "parent_id": child_id,
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_breadcrumbs_return_path_from_root() -> None:
    root_id = "10000000-0000-0000-0000-000000000011"
    child_id = "10000000-0000-0000-0000-000000000012"
    FakeB2BClient.categories = [
        _category(root_id, name="Electronics", slug="electronics"),
        _category(child_id, name="Phones", slug="phones", parent_id=root_id),
    ]

    response = TestClient(app).get(
        "/api/v1/breadcrumbs",
        params={"category_id": child_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": root_id,
                "slug": "electronics",
                "name": "Electronics",
                "url": "/catalog/electronics",
                "level": 0,
                "is_current": False,
            },
            {
                "id": child_id,
                "slug": "phones",
                "name": "Phones",
                "url": "/catalog/electronics/phones",
                "level": 1,
                "is_current": True,
            },
        ],
        "meta": {
            "resolved_via": "category_id",
            "category_id": child_id,
        },
    }


def test_category_detail_returns_metadata() -> None:
    root_id = "10000000-0000-0000-0000-000000000013"
    child_id = "10000000-0000-0000-0000-000000000014"
    FakeB2BClient.categories = [
        _category(root_id, name="Electronics", slug="electronics"),
        _category(child_id, name="Phones", slug="phones", parent_id=root_id),
    ]
    FakeB2BClient.products = [
        _product(
            "00000000-0000-0000-0000-000000000014",
            title="Phone",
            category_id=child_id,
            category="Phones",
            price=1000,
        )
    ]

    response = TestClient(app).get(
        f"/api/v1/categories/{child_id}",
        params={"include_product_count": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == child_id
    assert body["parent"] == {
        "id": root_id,
        "name": "Electronics",
        "slug": "electronics",
    }
    assert body["product_count"] == 1


def test_breadcrumbs_resolve_product_category() -> None:
    root_id = "10000000-0000-0000-0000-000000000015"
    child_id = "10000000-0000-0000-0000-000000000016"
    product_id = "00000000-0000-0000-0000-000000000016"
    FakeB2BClient.categories = [
        _category(root_id, name="Electronics", slug="electronics"),
        _category(child_id, name="Phones", slug="phones", parent_id=root_id),
    ]
    FakeB2BClient.products = [
        _product(
            product_id,
            title="Phone",
            category_id=child_id,
            category="Phones",
            price=1000,
        )
    ]

    response = TestClient(app).get(
        "/api/v1/breadcrumbs",
        params={"product_id": product_id},
    )

    assert response.status_code == 200
    assert response.json()["meta"] == {
        "resolved_via": "product_id",
        "category_id": child_id,
        "product_id": product_id,
    }
    assert [item["slug"] for item in response.json()["data"]] == [
        "electronics",
        "phones",
    ]


def test_unknown_category_returns_404() -> None:
    category_id = "10000000-0000-0000-0000-000000000404"

    response = TestClient(app).get(f"/api/v1/categories/{category_id}")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Category not found",
    }


def test_orphan_node_returns_422() -> None:
    child_id = "10000000-0000-0000-0000-000000000021"
    missing_parent_id = "10000000-0000-0000-0000-000000000022"
    FakeB2BClient.categories = [
        _category(
            child_id,
            name="Phones",
            slug="phones",
            parent_id=missing_parent_id,
        )
    ]

    response = TestClient(app).get("/api/v1/categories")

    assert response.status_code == 422
    assert response.json() == {
        "error": "orphan_node",
        "message": "category hierarchy is broken",
    }


def test_ambiguous_params_returns_400() -> None:
    category_id = "10000000-0000-0000-0000-000000000031"
    product_id = "00000000-0000-0000-0000-000000000031"

    response = TestClient(app).get(
        "/api/v1/breadcrumbs",
        params={"category_id": category_id, "product_id": product_id},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "ambiguous_param",
        "message": "only one of category_id or product_id must be provided",
    }


def test_missing_param_returns_400() -> None:
    response = TestClient(app).get("/api/v1/breadcrumbs")

    assert response.status_code == 400
    assert response.json() == {
        "error": "missing_param",
        "message": "category_id or product_id must be provided",
    }


@pytest.mark.asyncio
async def test_b2b_public_catalog_uses_service_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def get(self, path: str, *, headers=None, **kwargs):
            captured_headers.update(headers or {})
            return FakeResponse()

    monkeypatch.setattr(b2b_client_module.httpx, "AsyncClient", FakeAsyncClient)

    async with B2BClient("http://b2b") as client:
        await client.get_public_products()

    assert captured_headers["X-Service-Key"] == "dev-service-key-change-in-production"


@pytest.mark.asyncio
async def test_product_card_returns_full_data_with_skus() -> None:
    FakeB2BClient.products = [
        {
            **_product(
                "p1",
                title="Premium keyboard",
                category_id="keyboards",
                category="Keyboards",
                price=15000,
            ),
            "images": [{"url": "https://cdn.test/main.jpg"}],
            "skus": [
                {
                    "id": "sku-p1-black",
                    "name": "Black",
                    "price": 15000,
                    "discount": 1000,
                    "active_quantity": 3,
                    "cost_price": 9000,
                    "reserved_quantity": 2,
                    "images": [{"url": "https://cdn.test/black.jpg"}],
                }
            ],
        }
    ]

    response = await CatalogService().get_product_card("p1")

    assert FakeB2BClient.get_product_calls == ["p1"]
    assert FakeB2BClient.get_public_products_calls == 0
    assert response["id"] == "p1"
    assert response["name"] == "Premium keyboard"
    assert response["description"] == "Premium keyboard description"
    assert response["images"] == [{"url": "https://cdn.test/main.jpg"}]
    assert response["skus"] == [
        {
            "id": "sku-p1-black",
            "name": "Black",
            "price": 15000,
            "discount": 1000,
            "available_quantity": 3,
            "in_stock": True,
            "images": [{"url": "https://cdn.test/black.jpg"}],
        }
    ]


@pytest.mark.asyncio
async def test_cost_price_absent_in_response() -> None:
    FakeB2BClient.products = [
        {
            **_product(
                "p1",
                title="Premium keyboard",
                category_id="keyboards",
                category="Keyboards",
                price=15000,
            ),
            "skus": [
                {
                    "id": "sku-p1-black",
                    "name": "Black",
                    "price": 15000,
                    "active_quantity": 3,
                    "cost_price": 9000,
                    "reserved_quantity": 2,
                    "images": [],
                }
            ],
        }
    ]

    response = await CatalogService().get_product_card("p1")

    assert "cost_price" not in response["skus"][0]
    assert "reserved_quantity" not in response["skus"][0]


@pytest.mark.asyncio
async def test_blocked_product_returns_404() -> None:
    FakeB2BClient.products = []

    with pytest.raises(HTTPException) as exc_info:
        await CatalogService().get_product_card("blocked-product")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


@pytest.mark.asyncio
async def test_product_card_http_404_returns_error_contract() -> None:
    FakeB2BClient.products = []

    response = TestClient(app).get("/api/v1/catalog/products/blocked-product")

    assert response.status_code == 404
    assert response.json() == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


@pytest.mark.asyncio
async def test_sku_without_stock_is_shown_as_unavailable() -> None:
    FakeB2BClient.products = [
        {
            **_product(
                "p1",
                title="Premium keyboard",
                category_id="keyboards",
                category="Keyboards",
                price=15000,
                active_quantity=0,
            ),
            "skus": [
                {
                    "id": "sku-p1-black",
                    "name": "Black",
                    "price": 15000,
                    "active_quantity": 0,
                    "images": [],
                }
            ],
        }
    ]

    response = await CatalogService().get_product_card("p1")

    assert response["skus"][0]["in_stock"] is False
    assert response["skus"][0]["available_quantity"] == 0


def test_similar_returns_up_to_8_from_same_category() -> None:
    current_id = "00000000-0000-0000-0000-000000000001"
    category_id = "10000000-0000-0000-0000-000000000001"
    current = _product(
        current_id,
        title="Current keyboard",
        category_id=category_id,
        category="Keyboards",
        price=1000,
    )
    same_category = [
        _product(
            f"00000000-0000-0000-0000-0000000001{i:02d}",
            title=f"Keyboard {i}",
            category_id=category_id,
            category="Keyboards",
            price=1000 + i,
        )
        for i in range(10)
    ]
    other_category = _product(
        "00000000-0000-0000-0000-000000000201",
        title="Mouse",
        category_id="10000000-0000-0000-0000-000000000002",
        category="Mice",
        price=900,
    )
    FakeB2BClient.products = [current, *same_category, other_category]

    response = TestClient(app).get(
        f"/api/v1/products/{current_id}/similar",
        params={"category": category_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 8
    assert body["total_count"] == 10
    assert body["limit"] == 8
    assert body["offset"] == 0
    assert current_id not in {item["id"] for item in body["items"]}
    assert {item["title"] for item in body["items"]} == {
        f"Keyboard {i}" for i in range(8)
    }
    assert FakeB2BClient.get_similar_products_calls == [
        (current_id, category_id, 8, 0)
    ]


def test_empty_category_returns_200_empty_list() -> None:
    current_id = "00000000-0000-0000-0000-000000000301"
    category_id = "10000000-0000-0000-0000-000000000003"
    FakeB2BClient.products = [
        _product(
            current_id,
            title="Current keyboard",
            category_id=category_id,
            category="Keyboards",
            price=1000,
        )
    ]

    response = TestClient(app).get(
        f"/api/v1/products/{current_id}/similar",
        params={"category": category_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total_count": 0,
        "limit": 8,
        "offset": 0,
    }


def test_unknown_product_returns_404() -> None:
    FakeB2BClient.products = []
    missing_id = "00000000-0000-0000-0000-000000000404"
    category_id = "10000000-0000-0000-0000-000000000004"

    response = TestClient(app).get(
        f"/api/v1/products/{missing_id}/similar",
        params={"category": category_id},
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Product not found",
    }


def test_similar_b2b_unavailable_returns_503() -> None:
    FakeB2BClient.unavailable = True
    product_id = "00000000-0000-0000-0000-000000000503"
    category_id = "10000000-0000-0000-0000-000000000005"

    response = TestClient(app).get(
        f"/api/v1/products/{product_id}/similar",
        params={"category": category_id},
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "B2B_UNAVAILABLE",
        "message": "B2B catalog is unavailable",
    }
