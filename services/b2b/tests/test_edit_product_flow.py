from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.clients.moderation import ModerationClient
from src.main import app
from src.models.product import ProductStatus
from src.schemas.product import ProductUpdate
from src.schemas.sku import SKUUpdate
from src.services import product_service as product_service_module
from src.services import sku_service as sku_service_module
from src.services.product_service import ProductService
from src.services.sku_service import SKUService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _sku(*, product_id: UUID, reserved_quantity: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        name="Keyboard / Black",
        price=129900,
        stock=10,
        reserved_quantity=reserved_quantity,
        images=["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
        is_active=True,
    )


def _product(
    *,
    product_id: UUID | None = None,
    seller_id: UUID,
    status: ProductStatus,
    skus: list[object] | None = None,
) -> SimpleNamespace:
    product_id = product_id or uuid4()
    return SimpleNamespace(
        id=product_id,
        seller_id=seller_id,
        title="Wireless keyboard",
        description="Old description",
        category_id=uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        status=status,
        category=None,
        is_active=False,
        deleted=False,
        blocking_reason=None,
        field_reports=[],
        skus=skus or [],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class FakeProductRepository:
    product: SimpleNamespace | None = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_with_skus(self, product_id: UUID) -> SimpleNamespace | None:
        if self.product and self.product.id == product_id:
            return self.product
        return None

    async def get_seller_product(
        self, product_id: UUID, seller_id: UUID
    ) -> SimpleNamespace | None:
        if self.product and self.product.id == product_id and self.product.seller_id == seller_id:
            return self.product
        return None


class FakeSKURepository:
    sku: SimpleNamespace | None = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_id(self, sku_id: UUID) -> SimpleNamespace | None:
        if self.sku and self.sku.id == sku_id:
            return self.sku
        return None


class FakeModerationClient:
    edited_events: list[dict[str, object]] = []

    def product_snapshot(self, product: object) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "status": product.status.value,
        }

    async def send_product_edited(
        self,
        product: object,
        *,
        json_before: dict[str, object],
    ) -> None:
        self.edited_events.append(
            {
                "event_type": "PRODUCT_EDITED",
                "payload": {
                    "product_id": str(product.id),
                    "seller_id": str(product.seller_id),
                    "json_before": deepcopy(json_before),
                    "json_after": self.product_snapshot(product),
                },
            }
        )


@pytest.fixture(autouse=True)
def patch_repositories(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.product = None
    FakeSKURepository.sku = None
    FakeModerationClient.edited_events = []
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )
    monkeypatch.setattr(
        product_service_module, "ModerationClient", FakeModerationClient, raising=False
    )
    monkeypatch.setattr(sku_service_module, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(sku_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        sku_service_module, "ModerationClient", FakeModerationClient, raising=False
    )


@pytest.mark.asyncio
async def test_edit_moderated_product_returns_to_on_moderation() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.MODERATED)
    FakeProductRepository.product = product

    updated = await ProductService(FakeSession()).update(
        product.id,
        seller_id,
        ProductUpdate(description="Fixed description"),
    )

    assert updated.status == ProductStatus.ON_MODERATION
    assert updated.description == "Fixed description"
    assert len(FakeModerationClient.edited_events) == 1
    event = FakeModerationClient.edited_events[0]
    assert event["event_type"] == "PRODUCT_EDITED"
    assert event["payload"]["json_before"]["status"] == "MODERATED"
    assert event["payload"]["json_after"]["status"] == "ON_MODERATION"


@pytest.mark.asyncio
async def test_edit_blocked_product_returns_to_on_moderation() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.BLOCKED)
    FakeProductRepository.product = product

    updated = await ProductService(FakeSession()).update(
        product.id,
        seller_id,
        ProductUpdate(
            images=[
                {
                    "url": "https://cdn.neomarket.test/products/fixed.jpg",
                    "ordering": 0,
                }
            ]
        ),
    )

    assert updated.status == ProductStatus.ON_MODERATION
    assert len(FakeModerationClient.edited_events) == 1


@pytest.mark.asyncio
async def test_reserves_preserved_after_sku_edit() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku = _sku(product_id=product_id, reserved_quantity=7)
    product = _product(
        product_id=product_id,
        seller_id=seller_id,
        status=ProductStatus.MODERATED,
        skus=[sku],
    )
    FakeProductRepository.product = product
    FakeSKURepository.sku = sku

    updated = await SKUService(FakeSession()).update(
        sku.id,
        seller_id,
        SKUUpdate(price=139900, stock=25),
    )

    assert updated.price == 139900
    assert updated.stock == 25
    assert updated.reserved_quantity == 7
    assert product.status == ProductStatus.ON_MODERATION
    assert len(FakeModerationClient.edited_events) == 1


@pytest.mark.asyncio
async def test_edit_hard_blocked_returns_403() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.HARD_BLOCKED)
    FakeProductRepository.product = product

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).update(
            product.id,
            seller_id,
            ProductUpdate(description="Cannot fix"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "PRODUCT_HARD_BLOCKED",
        "message": "Cannot edit hard-blocked product",
    }


@pytest.mark.asyncio
async def test_edit_others_product_returns_403() -> None:
    product = _product(seller_id=uuid4(), status=ProductStatus.MODERATED)
    FakeProductRepository.product = product

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).update(
            product.id,
            uuid4(),
            ProductUpdate(description="IDOR attempt"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "PRODUCT_ACCESS_DENIED",
        "message": "Access denied",
    }


async def _fake_db():
    yield FakeSession()


def _fake_seller(seller_id: UUID):
    async def dependency():
        return SimpleNamespace(id=seller_id, is_active=True)

    return dependency


def test_update_product_response_matches_contract() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.MODERATED)
    FakeProductRepository.product = product
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(
        seller_id
    )
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).put(
            f"/api/v1/products/{product.id}",
            json={
                "description": "Fixed description",
                "images": [
                    {
                        "url": "https://cdn.neomarket.test/products/fixed.jpg",
                        "ordering": 0,
                    }
                ],
                "characteristics": [{"name": "layout", "value": "ISO"}],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ON_MODERATION"
    assert body["slug"].startswith("wireless-keyboard-")
    assert body["images"] == [
        {
            "id": body["images"][0]["id"],
            "url": "https://cdn.neomarket.test/products/fixed.jpg",
            "ordering": 0,
        }
    ]
    assert body["characteristics"] == [{"name": "layout", "value": "ISO"}]
    assert body["blocking_reason_id"] is None
    assert body["moderator_comment"] is None
    assert "created_at" in body
    assert "updated_at" in body
    assert "category" not in body
    assert "is_active" not in body


def test_update_hard_blocked_product_error_matches_contract() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.HARD_BLOCKED)
    FakeProductRepository.product = product
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(
        seller_id
    )
    app.dependency_overrides[products_router.get_db] = _fake_db
    try:
        response = TestClient(app).put(
            f"/api/v1/products/{product.id}",
            json={"description": "Cannot fix"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {
        "code": "PRODUCT_HARD_BLOCKED",
        "message": "Cannot edit hard-blocked product",
    }


def test_product_edited_event_matches_moderation_contract() -> None:
    seller_id = uuid4()
    product = _product(seller_id=seller_id, status=ProductStatus.ON_MODERATION)
    json_before = {
        "id": str(product.id),
        "seller_id": str(seller_id),
        "status": "MODERATED",
    }

    event = ModerationClient().build_product_edited_event(
        product,
        json_before=json_before,
    )

    assert event["event_type"] == "PRODUCT_EDITED"
    assert UUID(event["idempotency_key"])
    assert event["payload"]["product_id"] == str(product.id)
    assert event["payload"]["seller_id"] == str(seller_id)
    assert event["payload"]["json_before"] == json_before
    assert event["payload"]["json_after"]["status"] == "ON_MODERATION"
