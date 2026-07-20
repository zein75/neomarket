from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.services import product_service as product_service_module
from src.services.product_service import ProductService


def _sku(product_id, *, cost_price: int = 90000, reserved_quantity: int = 2):
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=129900,
        cost_price=cost_price,
        stock=10,
        reserved_quantity=reserved_quantity,
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _product(*, seller_id, status=ProductStatus.MODERATED, **overrides):
    product_id = uuid4()
    product = SimpleNamespace(
        id=product_id,
        seller_id=seller_id,
        title="Wireless keyboard",
        description="Low-profile keyboard",
        category_id=uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        status=status,
        category=None,
        is_active=True,
        deleted=False,
        blocking_reason=None,
        field_reports=[],
        skus=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    product.skus = [_sku(product_id)]
    for key, value in overrides.items():
        setattr(product, key, value)
    return product


class FakeProductRepository:
    product = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_with_skus(self, product_id):
        if self.product and self.product.id == product_id:
            return self.product
        return None


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.product = None
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )


@pytest.mark.asyncio
async def test_get_moderated_product_returns_full_payload() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id)
    FakeProductRepository.product = product

    body = await ProductService(SimpleNamespace()).get_for_seller(product.id, seller_id)

    assert body["id"] == str(product.id)
    assert body["seller_id"] == str(seller_id)
    assert body["title"] == "Wireless keyboard"
    assert body["description"] == "Low-profile keyboard"
    assert body["status"] == "MODERATED"
    assert body["slug"].startswith("wireless-keyboard-")
    assert body["images"][0]["url"] == "https://cdn.neomarket.test/products/keyboard.jpg"
    assert body["images"][0]["ordering"] == 0
    assert body["characteristics"] == [{"name": "layout", "value": "US"}]
    assert body["created_at"] == product.created_at
    assert body["updated_at"] == product.updated_at
    assert body["blocked"] is False
    assert body["blocking_reason"] is None
    assert body["field_reports"] == []
    assert body["skus"][0]["cost_price"] == 90000
    assert body["skus"][0]["reserved_quantity"] == 2


@pytest.mark.asyncio
async def test_get_blocked_product_returns_blocking_reason_and_field_reports() -> None:
    seller_id = uuid4()
    product = _product(
        seller_id=seller_id,
        status="BLOCKED",
        blocking_reason={
            "id": str(uuid4()),
            "title": "Bad photos",
            "comment": "Photo must show the product clearly",
        },
        field_reports=[
            {
                "field_name": "images[0]",
                "sku_id": None,
                "comment": "Image is blurry",
            }
        ],
    )
    FakeProductRepository.product = product

    body = await ProductService(SimpleNamespace()).get_for_seller(product.id, seller_id)

    assert body["status"] == "BLOCKED"
    assert body["blocked"] is True
    assert body["blocking_reason"]["title"] == "Bad photos"
    assert body["field_reports"] == [
        {
            "field_name": "images[0]",
            "sku_id": None,
            "comment": "Image is blurry",
        }
    ]


@pytest.mark.asyncio
async def test_get_others_product_returns_404() -> None:
    product = _product(seller_id=uuid4())
    FakeProductRepository.product = product

    with pytest.raises(Exception) as exc_info:
        await ProductService(SimpleNamespace()).get_for_seller(product.id, uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404() -> None:
    with pytest.raises(Exception) as exc_info:
        await ProductService(SimpleNamespace()).get_for_seller(uuid4(), uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


async def _fake_db():
    yield SimpleNamespace()


def _fake_seller(seller_id):
    async def dependency():
        return SimpleNamespace(id=seller_id, is_active=True)

    return dependency


def test_get_others_product_response_matches_error_contract() -> None:
    product = _product(seller_id=uuid4())
    FakeProductRepository.product = product
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(
        uuid4()
    )
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).get(f"/api/v1/products/{product.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


def test_get_nonexistent_response_matches_error_contract() -> None:
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(
        uuid4()
    )
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).get(f"/api/v1/products/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }


def test_public_product_response_does_not_expose_seller_sku_fields() -> None:
    product = _product(seller_id=uuid4())
    FakeProductRepository.product = product
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).get(
            f"/products/{product.id}",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["slug"].startswith("wireless-keyboard-")
    assert body["images"][0]["url"] == "https://cdn.neomarket.test/products/keyboard.jpg"
    assert body["characteristics"] == [{"name": "layout", "value": "US"}]
    assert "cost_price" not in body["skus"][0]
    assert "reserved_quantity" not in body["skus"][0]
