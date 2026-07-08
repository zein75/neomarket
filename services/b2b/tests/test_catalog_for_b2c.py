from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.services import product_service as product_service_module
from src.services.product_service import ProductService


def _sku(*, product_id, stock=10, reserved_quantity=2, cost_price=70000):
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=129900,
        cost_price=cost_price,
        stock=stock,
        reserved_quantity=reserved_quantity,
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
    )


def _product(*, status=ProductStatus.MODERATED, deleted=False, stock=10, reserved=2):
    product_id = uuid4()
    return SimpleNamespace(
        id=product_id,
        seller_id=uuid4(),
        title="Wireless keyboard",
        description="Low-profile keyboard",
        category_id=uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        status=status,
        category=None,
        is_active=True,
        deleted=deleted,
        skus=[_sku(product_id=product_id, stock=stock, reserved_quantity=reserved)],
    )


class FakeProductRepository:
    products: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_public_catalog(self, product_ids=None):
        if product_ids is None:
            return list(self.products)
        return [product for product in self.products if product.id in product_ids]


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.products = []
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )


@pytest.mark.asyncio
async def test_catalog_returns_moderated_in_stock_products() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=2)
    out_of_stock = _product(status=ProductStatus.MODERATED, deleted=False, stock=2, reserved=2)
    deleted = _product(status=ProductStatus.MODERATED, deleted=True, stock=5, reserved=0)
    blocked = _product(status=ProductStatus.BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [visible, out_of_stock, deleted, blocked]

    body = await ProductService(SimpleNamespace()).list_public_catalog()

    assert [item["id"] for item in body] == [str(visible.id)]


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

    assert body == []


def test_catalog_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).get("/api/v1/products")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_response_has_no_cost_price() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=1)
    FakeProductRepository.products = [visible]

    body = await ProductService(SimpleNamespace()).list_public_catalog()

    assert "cost_price" not in body[0]["skus"][0]
    assert "reserved_quantity" not in body[0]["skus"][0]


@pytest.mark.asyncio
async def test_batch_ids_returns_visible_subset() -> None:
    visible = _product(status=ProductStatus.MODERATED, deleted=False, stock=5, reserved=0)
    hidden = _product(status=ProductStatus.HARD_BLOCKED, deleted=False, stock=5, reserved=0)
    FakeProductRepository.products = [visible, hidden]

    body = await ProductService(SimpleNamespace()).list_public_catalog(
        product_ids=[visible.id, hidden.id, uuid4()]
    )

    assert [item["id"] for item in body] == [str(visible.id)]
