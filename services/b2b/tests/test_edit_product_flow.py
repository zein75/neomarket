from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.clients.moderation import ModerationClient
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
        skus=skus or [],
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
