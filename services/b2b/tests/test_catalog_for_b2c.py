from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.routers import categories as categories_router
from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.services import category_service as category_service_module
from src.services import product_service as product_service_module
from src.services.category_service import CategoryService
from src.services.product_service import ProductService


def _sku(
    *,
    product_id,
    stock=10,
    reserved_quantity=2,
    cost_price=70000,
    price=129900,
    characteristics=None,
):
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=price,
        cost_price=cost_price,
        stock=stock,
        reserved_quantity=reserved_quantity,
        characteristics=characteristics or {},
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
    )


def _product(
    *,
    status=ProductStatus.MODERATED,
    deleted=False,
    stock=10,
    reserved=2,
    title="Wireless keyboard",
    description="Low-profile keyboard",
    category_id=None,
    seller_id=None,
    price=129900,
):
    product_id = uuid4()
    return SimpleNamespace(
        id=product_id,
        seller_id=seller_id or uuid4(),
        title=title,
        description=description,
        category_id=category_id or uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        status=status,
        category=None,
        is_active=True,
        deleted=deleted,
        skus=[
            _sku(
                product_id=product_id,
                stock=stock,
                reserved_quantity=reserved,
                characteristics={"color": "Black"},
                price=price,
            )
        ],
    )


def _category(*, category_id=None, name="Electronics", slug="electronics", parent_id=None):
    return SimpleNamespace(
        id=category_id or uuid4(),
        name=name,
        slug=slug,
        parent_id=parent_id,
        is_active=True,
    )


class FakeProductRepository:
    products: list[SimpleNamespace] = []
    category_parents: dict[object, object | None] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_public_catalog(self, product_ids=None):
        if product_ids is None:
            return list(self.products)
        return [product for product in self.products if product.id in product_ids]

    async def get_with_skus(self, product_id):
        return next((product for product in self.products if product.id == product_id), None)

    async def get_category_parent_id(self, category_id):
        return self.category_parents.get(category_id)

    async def list_category_ids_by_parent(self, parent_id):
        return [
            category_id
            for category_id, current_parent_id in self.category_parents.items()
            if current_parent_id == parent_id
        ]

    async def category_exists(self, category_id):
        if any(product.category_id == category_id for product in self.products):
            return True
        if category_id in self.category_parents:
            return True
        return category_id in self.category_parents.values()


class FakeCategoryRepository:
    categories: list[SimpleNamespace] = []
    product_counts: dict[object, int] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active(self):
        return list(self.categories)

    async def get_active(self, category_id):
        return next(
            (category for category in self.categories if category.id == category_id),
            None,
        )

    async def count_public_products(self, category_id):
        return self.product_counts.get(category_id, 0)


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.products = []
    FakeProductRepository.category_parents = {}
    FakeCategoryRepository.categories = []
    FakeCategoryRepository.product_counts = {}
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )
    monkeypatch.setattr(
        category_service_module, "CategoryRepository", FakeCategoryRepository
    )


@pytest.mark.asyncio
async def test_public_categories_list_returns_flat_categories() -> None:
    root = _category(name="Electronics", slug="electronics")
    child = _category(name="Phones", slug="phones", parent_id=root.id)
    FakeCategoryRepository.categories = [root, child]

    body = await CategoryService(SimpleNamespace()).list_active()

    assert [item.id for item in body.items] == [root.id, child.id]
    assert body.items[1].parent_id == root.id


@pytest.mark.asyncio
async def test_public_category_detail_returns_parent_and_product_count() -> None:
    root = _category(name="Electronics", slug="electronics")
    child = _category(name="Phones", slug="phones", parent_id=root.id)
    FakeCategoryRepository.categories = [root, child]
    FakeCategoryRepository.product_counts = {child.id: 7}

    body = await CategoryService(SimpleNamespace()).get_detail(
        child.id,
        include_product_count=True,
    )

    assert body.id == child.id
    assert body.parent is not None
    assert body.parent.id == root.id
    assert body.product_count == 7


def test_public_categories_route_requires_service_key() -> None:
    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[categories_router.get_db] = fake_db
    try:
        response = TestClient(app).get("/api/v1/public/categories")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_returns_moderated_in_stock_products() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=2)
    out_of_stock = _product(status=ProductStatus.MODERATED, deleted=False, stock=2, reserved=2)
    deleted = _product(status=ProductStatus.MODERATED, deleted=True, stock=5, reserved=0)
    blocked = _product(status=ProductStatus.BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [visible, out_of_stock, deleted, blocked]

    body = await ProductService(SimpleNamespace()).list_public_catalog()

    assert [str(item.id) for item in body.items] == [str(visible.id)]
    assert body.total_count == 1
    assert body.limit == 20
    assert body.offset == 0


@pytest.mark.asyncio
async def test_catalog_excludes_hard_blocked() -> None:
    hard_blocked = _product(
        status=ProductStatus.HARD_BLOCKED,
        deleted=False,
        stock=5,
        reserved=0,
    )
    FakeProductRepository.products = [hard_blocked]

    body = await ProductService(SimpleNamespace()).list_public_catalog()

    assert body.items == []
    assert body.total_count == 0


def test_catalog_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).get("/api/v1/public/products")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_response_has_no_cost_price() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    FakeProductRepository.products = [visible]

    body = await ProductService(SimpleNamespace()).list_public_catalog()

    item = body.items[0].model_dump()
    assert item["slug"].startswith("wireless-keyboard-")
    assert item["skus"][0]["price"] == 129900
    assert item["skus"][0]["characteristics"] == [{"name": "color", "value": "Black"}]
    assert "created_at" in item
    assert "cost_price" not in item["skus"][0]
    assert "reserved_quantity" not in item["skus"][0]


def test_public_catalog_route_returns_contract_envelope() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    FakeProductRepository.products = [visible]

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).get(
            "/api/v1/public/products",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["items"][0]["slug"].startswith("wireless-keyboard-")
    assert body["items"][0]["skus"][0]["price"] == 129900
    assert body["items"][0]["skus"][0]["characteristics"] == [
        {"name": "color", "value": "Black"}
    ]
    assert "cost_price" not in body["items"][0]["skus"][0]
    assert "reserved_quantity" not in body["items"][0]["skus"][0]
    assert "created_at" in body["items"][0]


def test_canonical_catalog_route_uses_service_key_and_public_shape() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    hidden = _product(status=ProductStatus.HARD_BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [hidden, visible]

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        missing_key = TestClient(app).get("/api/v1/products")
        response = TestClient(app).get(
            f"/api/v1/products?ids={hidden.id},{visible.id},{uuid4()}",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_key.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(visible.id)]
    assert body["total_count"] == 1
    sku = body["items"][0]["skus"][0]
    assert sku["characteristics"] == [{"name": "color", "value": "Black"}]
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku


def test_legacy_products_route_requires_service_key_and_uses_public_shape() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    FakeProductRepository.products = [visible]

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        missing_key = TestClient(app).get("/products")
        response = TestClient(app).get(
            "/products",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_key.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert body["items"][0]["slug"].startswith("wireless-keyboard-")
    sku = body["items"][0]["skus"][0]
    assert sku["characteristics"] == [{"name": "color", "value": "Black"}]
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku


def test_public_product_detail_route_uses_public_sku_shape() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    FakeProductRepository.products = [visible]

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).get(
            f"/api/v1/public/products/{visible.id}",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    sku = response.json()["skus"][0]
    assert sku["stock_quantity"] == 5
    assert sku["discount"] == 0
    assert sku["article"] is None
    assert sku["characteristics"] == [{"name": "color", "value": "Black"}]
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku


def test_public_products_batch_route_returns_visible_public_details() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    hidden = _product(status=ProductStatus.BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [hidden, visible]

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/public/products/batch",
            json={"product_ids": [str(hidden.id), str(visible.id), str(uuid4())]},
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(visible.id)]
    assert body[0]["slug"].startswith("wireless-keyboard-")
    assert body[0]["created_at"]
    sku = body[0]["skus"][0]
    assert sku["stock_quantity"] == 5
    assert sku["discount"] == 0
    assert sku["article"] is None
    assert sku["characteristics"] == [{"name": "color", "value": "Black"}]
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku


@pytest.mark.asyncio
async def test_batch_ids_returns_visible_subset() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=0)
    hidden = _product(status=ProductStatus.HARD_BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [visible, hidden]

    body = await ProductService(SimpleNamespace()).list_public_catalog(
        product_ids=[visible.id, hidden.id, uuid4()]
    )

    assert [str(item.id) for item in body.items] == [str(visible.id)]
    assert body.total_count == 1


@pytest.mark.asyncio
async def test_public_catalog_applies_filters_sort_and_pagination() -> None:
    category_id = uuid4()
    seller_id = uuid4()
    matched_high = _product(
        title="Premium keyboard",
        category_id=category_id,
        seller_id=seller_id,
        price=15000,
        stock=5,
        reserved=0,
    )
    matched_low = _product(
        title="Budget keyboard",
        category_id=category_id,
        seller_id=seller_id,
        price=7000,
        stock=5,
        reserved=0,
    )
    wrong_category = _product(
        title="Premium keyboard",
        seller_id=seller_id,
        price=20000,
        stock=5,
        reserved=0,
    )
    FakeProductRepository.products = [matched_low, wrong_category, matched_high]

    body = await ProductService(SimpleNamespace()).list_public_catalog(
        category_id=category_id,
        search="keyboard",
        min_price=6000,
        max_price=16000,
        seller_id=seller_id,
        in_stock=True,
        sort="price_desc",
        limit=1,
        offset=0,
    )

    assert [str(item.id) for item in body.items] == [str(matched_high.id)]
    assert body.total_count == 2
    assert body.limit == 1
    assert body.offset == 0


@pytest.mark.asyncio
async def test_public_catalog_search_matches_title_and_description() -> None:
    title_match = _product(title="Wireless keyboard", description="Office device")
    description_match = _product(title="Office device", description="Low keyboard")
    miss = _product(title="Mouse", description="Pointing device")
    FakeProductRepository.products = [title_match, description_match, miss]

    body = await ProductService(SimpleNamespace()).list_public_catalog(
        search="keyboard",
    )

    assert [str(item.id) for item in body.items] == [
        str(title_match.id),
        str(description_match.id),
    ]


@pytest.mark.asyncio
async def test_public_similar_returns_same_category_without_current() -> None:
    category_id = uuid4()
    current = _product(title="Current keyboard", category_id=category_id)
    same_category = [
        _product(title=f"Keyboard {idx}", category_id=category_id)
        for idx in range(10)
    ]
    other_category = _product(title="Mouse")
    FakeProductRepository.products = [current, *same_category, other_category]

    body = await ProductService(SimpleNamespace()).list_similar_public(
        current.id,
        category_id=category_id,
    )

    assert len(body.items) == 8
    assert body.total_count == 10
    assert str(current.id) not in {str(item.id) for item in body.items}
    assert {str(item.category_id) for item in body.items} == {str(category_id)}


@pytest.mark.asyncio
async def test_public_similar_falls_back_to_parent_category() -> None:
    parent_id = uuid4()
    current_category_id = uuid4()
    sibling_category_id = uuid4()
    current = _product(title="Current keyboard", category_id=current_category_id)
    same_category = _product(title="Same category", category_id=current_category_id)
    sibling_category = _product(title="Sibling category", category_id=sibling_category_id)
    unrelated = _product(title="Unrelated")
    FakeProductRepository.products = [
        current,
        same_category,
        sibling_category,
        unrelated,
    ]
    FakeProductRepository.category_parents = {
        current_category_id: parent_id,
        sibling_category_id: parent_id,
    }

    body = await ProductService(SimpleNamespace()).list_similar_public(
        current.id,
        category_id=current_category_id,
    )

    assert [str(item.id) for item in body.items] == [
        str(same_category.id),
        str(sibling_category.id),
    ]


@pytest.mark.asyncio
async def test_public_similar_unknown_category_returns_400() -> None:
    current = _product(title="Current keyboard")
    FakeProductRepository.products = [current]

    with pytest.raises(HTTPException) as exc_info:
        await ProductService(SimpleNamespace()).list_similar_public(
            current.id,
            category_id=uuid4(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "code": "INVALID_REQUEST",
        "message": "Nonexistent category id",
    }
