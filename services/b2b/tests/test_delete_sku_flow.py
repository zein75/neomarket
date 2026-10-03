from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import skus as skus_router
from src.main import app
from src.models.product import ProductStatus
from src.services import sku_service as sku_service_module
from src.services.sku_service import SKUService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _sku(
    *,
    product_id: UUID,
    stock: int = 10,
    reserved_quantity: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=129900,
        stock=stock,
        reserved_quantity=reserved_quantity,
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
    )


def _product(
    *,
    product_id: UUID | None = None,
    seller_id: UUID,
    status: ProductStatus = ProductStatus.MODERATED,
    skus: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    product_id = product_id or uuid4()
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
        deleted=False,
        skus=skus or [],
    )


class FakeProductRepository:
    product: SimpleNamespace | None = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_seller_product(
        self,
        product_id: UUID,
        seller_id: UUID,
    ) -> SimpleNamespace | None:
        if (
            self.product
            and self.product.id == product_id
            and self.product.seller_id == seller_id
        ):
            return self.product
        return None


class FakeSKURepository:
    skus: dict[UUID, SimpleNamespace] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_id(self, sku_id: UUID) -> SimpleNamespace | None:
        return self.skus.get(sku_id)

    async def delete(self, sku: SimpleNamespace) -> None:
        self.skus.pop(sku.id, None)
        await self.session.flush()


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
    out_of_stock_events: list[dict[str, object]] = []

    async def send_sku_out_of_stock(self, sku: object) -> None:
        self.out_of_stock_events.append(
            {
                "event_type": "SKU_OUT_OF_STOCK",
                "payload": {"sku_id": str(sku.id)},
            }
        )


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.product = None
    FakeSKURepository.skus = {}
    FakeModerationClient.deleted_events = []
    FakeB2CClient.out_of_stock_events = []
    monkeypatch.setattr(sku_service_module, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(sku_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        sku_service_module, "ModerationClient", FakeModerationClient, raising=False
    )
    monkeypatch.setattr(sku_service_module, "B2CClient", FakeB2CClient, raising=False)


@pytest.mark.asyncio
async def test_delete_sku_succeeds() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    removed = _sku(product_id=product_id)
    remaining = _sku(product_id=product_id)
    product = _product(seller_id=seller_id, product_id=product_id, skus=[removed, remaining])
    FakeProductRepository.product = product
    FakeSKURepository.skus = {removed.id: removed, remaining.id: remaining}

    await SKUService(FakeSession()).delete(removed.id, seller_id)

    assert removed.id not in FakeSKURepository.skus
    assert product.skus == [remaining]


@pytest.mark.asyncio
async def test_delete_sku_with_active_reserves_returns_409() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, reserved_quantity=2)
    product = _product(seller_id=seller_id, product_id=product_id, skus=[sku])
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    with pytest.raises(Exception) as exc_info:
        await SKUService(FakeSession()).delete(sku.id, seller_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "SKU_ACTIVE_RESERVES",
        "message": "Cannot delete SKU with active reserves",
    }
    assert sku.id in FakeSKURepository.skus


@pytest.mark.asyncio
async def test_last_sku_on_moderation_transitions_product_to_created() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id)
    product = _product(
        seller_id=seller_id,
        product_id=product_id,
        status=ProductStatus.ON_MODERATION,
        skus=[sku],
    )
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    await SKUService(FakeSession()).delete(sku.id, seller_id)

    assert product.status == ProductStatus.CREATED
    assert product.skus == []
    assert FakeModerationClient.deleted_events == [
        {
            "event_type": "PRODUCT_DELETED",
            "payload": {"product_id": str(product.id)},
        }
    ]


@pytest.mark.asyncio
async def test_delete_sku_hard_blocked_product_returns_403() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, reserved_quantity=2)
    product = _product(
        seller_id=seller_id,
        product_id=product_id,
        status=ProductStatus.HARD_BLOCKED,
        skus=[sku],
    )
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    with pytest.raises(Exception) as exc_info:
        await SKUService(FakeSession()).delete(sku.id, seller_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "SKU_HARD_BLOCKED_PRODUCT",
        "message": "Cannot delete SKU of hard-blocked product",
    }
    assert sku.id in FakeSKURepository.skus


@pytest.mark.asyncio
async def test_sku_out_of_stock_event_on_moderated_product() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, stock=5, reserved_quantity=0)
    product = _product(
        seller_id=seller_id,
        product_id=product_id,
        status=ProductStatus.MODERATED,
        skus=[sku],
    )
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    await SKUService(FakeSession()).delete(sku.id, seller_id)

    assert FakeB2CClient.out_of_stock_events == [
        {
            "event_type": "SKU_OUT_OF_STOCK",
            "payload": {"sku_id": str(sku.id)},
        }
    ]


def test_delete_sku_with_active_reserves_returns_error_contract() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, reserved_quantity=2)
    product = _product(seller_id=seller_id, product_id=product_id, skus=[sku])
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    async def fake_current_seller():
        return SimpleNamespace(id=seller_id, is_active=True)

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[skus_router.get_current_seller] = fake_current_seller
    app.dependency_overrides[skus_router.get_db] = fake_db
    try:
        response = TestClient(app).delete(f"/api/v1/skus/{sku.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {
        "code": "SKU_ACTIVE_RESERVES",
        "message": "Cannot delete SKU with active reserves",
    }


def test_delete_sku_hard_blocked_product_returns_error_contract() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, reserved_quantity=2)
    product = _product(
        seller_id=seller_id,
        product_id=product_id,
        status=ProductStatus.HARD_BLOCKED,
        skus=[sku],
    )
    FakeProductRepository.product = product
    FakeSKURepository.skus = {sku.id: sku}

    async def fake_current_seller():
        return SimpleNamespace(id=seller_id, is_active=True)

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[skus_router.get_current_seller] = fake_current_seller
    app.dependency_overrides[skus_router.get_db] = fake_db
    try:
        response = TestClient(app).delete(f"/api/v1/skus/{sku.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {
        "code": "SKU_HARD_BLOCKED_PRODUCT",
        "message": "Cannot delete SKU of hard-blocked product",
    }
