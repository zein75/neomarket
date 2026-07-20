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
        "description": f"{title} description",
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


class FakeB2BClient:
    products: list[dict[str, object]] = []
    unavailable = False
    get_public_products_calls = 0
    last_public_products_kwargs: dict[str, object] = {}
    get_product_calls: list[str] = []

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
                if str(search).lower() in str(product.get("title", "")).lower()
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


@pytest.fixture(autouse=True)
def patch_b2b(monkeypatch: pytest.MonkeyPatch):
    FakeB2BClient.products = []
    FakeB2BClient.unavailable = False
    FakeB2BClient.get_public_products_calls = 0
    FakeB2BClient.last_public_products_kwargs = {}
    FakeB2BClient.get_product_calls = []
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
