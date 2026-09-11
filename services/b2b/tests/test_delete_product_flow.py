from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.services import product_service as product_service_module
from src.services.product_service import ProductService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _sku(product_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=129900,
        stock=10,
        reserved_quantity=0,
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
    )


def _product(
    *,
    seller_id: UUID,
    deleted: bool = False,
    status: ProductStatus = ProductStatus.MODERATED,
) -> SimpleNamespace:
    product_id = uuid4()
    return SimpleNamespace(
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
        deleted=deleted,
        skus=[_sku(product_id), _sku(product_id)],
    )


class FakeProductRepository:
    products: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_with_skus(self, product_id: UUID) -> SimpleNamespace | None:
        return next((product for product in self.products if product.id == product_id), None)

    async def get_seller_product(
        self, product_id: UUID, seller_id: UUID
    ) -> SimpleNamespace | None:
        return next(
            (
                product
                for product in self.products
                if product.id == product_id and product.seller_id == seller_id
            ),
            None,
        )

    async def list_by_seller(self, seller_id: UUID) -> list[SimpleNamespace]:
        return [
            product
            for product in self.products
            if product.seller_id == seller_id and not product.deleted
        ]

    async def delete(self, product: SimpleNamespace) -> None:
        self.products.remove(product)


class FakeModerationClient:
    deleted_events: list[dict[str, object]] = []

    async def send_product_deleted(self, product: object) -> None:
        self.deleted_events.append(
            {
                "event_type": "PRODUCT_DELETED",
                "payload": {"product_id": str(product.id)},
            }
        )


class FakeB2CClient:
    deleted_events: list[dict[str, object]] = []

    async def send_product_deleted(self, product: object) -> None:
        self.deleted_events.append(
            {
                "event_type": "PRODUCT_DELETED",
                "payload": {
                    "product_id": str(product.id),
                    "reason": "PRODUCT_DELETED",
                },
            }
        )


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.products = []
    FakeModerationClient.deleted_events = []
    FakeB2CClient.deleted_events = []
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )
    monkeypatch.setattr(
        product_service_module, "ModerationClient", FakeModerationClient, raising=False
    )
    monkeypatch.setattr(
        product_service_module, "B2CClient", FakeB2CClient, raising=False
    )


@pytest.mark.asyncio
async def test_delete_sets_deleted_true() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id)
    FakeProductRepository.products = [product]

    await ProductService(FakeSession()).delete(product.id, seller_id)

    assert product.deleted is True
    assert product.is_active is False


@pytest.mark.asyncio
async def test_delete_emits_event_to_moderation() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id)
    FakeProductRepository.products = [product]

    await ProductService(FakeSession()).delete(product.id, seller_id)

    assert FakeModerationClient.deleted_events == [
        {
            "event_type": "PRODUCT_DELETED",
            "payload": {"product_id": str(product.id)},
        }
    ]


@pytest.mark.asyncio
async def test_delete_emits_product_deleted_to_b2c() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id)
    FakeProductRepository.products = [product]

    await ProductService(FakeSession()).delete(product.id, seller_id)

    assert FakeB2CClient.deleted_events == [
        {
            "event_type": "PRODUCT_DELETED",
            "payload": {
                "product_id": str(product.id),
                "reason": "PRODUCT_DELETED",
            },
        }
    ]


@pytest.mark.asyncio
async def test_delete_already_deleted_returns_400() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, deleted=True)
    FakeProductRepository.products = [product]

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).delete(product.id, seller_id)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "code": "INVALID_REQUEST",
        "message": "Product already deleted",
    }


@pytest.mark.asyncio
async def test_delete_others_product_returns_403() -> None:
    product = _product(seller_id=uuid4())
    FakeProductRepository.products = [product]

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).delete(product.id, uuid4())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "PRODUCT_ACCESS_DENIED",
        "message": "Access denied",
    }


@pytest.mark.asyncio
async def test_delete_hard_blocked_product_returns_403() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.HARD_BLOCKED)
    FakeProductRepository.products = [product]

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).delete(product.id, seller_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "PRODUCT_HARD_BLOCKED",
        "message": "Cannot delete hard-blocked product",
    }


async def _fake_db():
    yield FakeSession()


def _fake_seller(seller_id: UUID):
    async def dependency():
        return SimpleNamespace(id=seller_id, is_active=True)

    return dependency


def test_delete_already_deleted_response_matches_contract() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, deleted=True)
    FakeProductRepository.products = [product]
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(
        seller_id
    )
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).delete(f"/api/v1/products/{product.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Product already deleted",
    }


def test_delete_others_product_response_matches_contract() -> None:
    product = _product(seller_id=uuid4())
    FakeProductRepository.products = [product]
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(uuid4())
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).delete(f"/api/v1/products/{product.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {
        "code": "PRODUCT_ACCESS_DENIED",
        "message": "Access denied",
    }


@pytest.mark.asyncio
async def test_deleted_product_not_in_seller_list() -> None:
    seller_id = uuid4()
    deleted_product = _product(seller_id=seller_id, deleted=True)
    active_product = _product(seller_id=seller_id)
    FakeProductRepository.products = [deleted_product, active_product]

    products = await ProductService(FakeSession()).list_by_seller(seller_id)

    assert products == [active_product]
