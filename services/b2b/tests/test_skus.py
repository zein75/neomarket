from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import skus as skus_router
from src.clients import moderation as moderation_module
from src.clients.moderation import ModerationClient
from src.main import app
from src.models.product import ProductStatus
from src.schemas.sku import SKUCreate
from src.services import sku_service as sku_service_module
from src.services.sku_service import SKUService


def _payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "product_id": str(uuid4()),
        "name": "Keyboard / Black",
        "price": 129900,
        "stock": 10,
        "images": ["https://cdn.neomarket.test/skus/keyboard-black.jpg"],
    }
    data.update(overrides)
    return data


def _product(
    *,
    product_id: UUID,
    seller_id: UUID,
    status: ProductStatus = ProductStatus.CREATED,
    skus: list[object] | None = None,
) -> SimpleNamespace:
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
        is_active=False,
        skus=skus or [],
    )


class FakeProductRepository:
    product: SimpleNamespace

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_seller_product(
        self, product_id: UUID, seller_id: UUID
    ) -> SimpleNamespace | None:
        if self.product.id == product_id and self.product.seller_id == seller_id:
            return self.product
        return None


class FakeSKURepository:
    created: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_by_product(self, product_id: UUID) -> list[object]:
        return list(FakeProductRepository.product.skus)

    async def create_sku(
        self,
        *,
        product_id: UUID,
        name: str,
        price: int,
        stock: int,
        images: list[str],
    ) -> SimpleNamespace:
        sku = SimpleNamespace(
            id=uuid4(),
            product_id=product_id,
            name=name,
            price=price,
            stock=stock,
            images=images,
            is_active=True,
        )
        self.created.append(sku)
        FakeProductRepository.product.skus.append(sku)
        return sku


class FakeModerationClient:
    events: list[dict[str, object]] = []

    async def send_product_created(self, product: object) -> None:
        self.events.append(self.build_product_created_event(product))

    def build_product_created_event(self, product: object) -> dict[str, object]:
        return {
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid4()),
            "payload": {
                "product_id": str(product.id),
                "seller_id": str(product.seller_id),
                "category_id": str(product.category_id),
                "json_after": {"status": product.status.value},
            },
        }


class FakeSession:
    async def flush(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch: pytest.MonkeyPatch):
    FakeSKURepository.created = []
    FakeModerationClient.events = []
    monkeypatch.setattr(sku_service_module, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(sku_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        sku_service_module, "ModerationClient", FakeModerationClient, raising=False
    )


@pytest.mark.asyncio
async def test_first_sku_transitions_product_to_on_moderation() -> None:
    product_id = uuid4()
    seller_id = uuid4()
    FakeProductRepository.product = _product(
        product_id=product_id, seller_id=seller_id
    )

    await SKUService(FakeSession()).create(
        seller_id, SKUCreate(**_payload(product_id=str(product_id)))
    )

    assert FakeProductRepository.product.status == ProductStatus.ON_MODERATION


@pytest.mark.asyncio
async def test_first_sku_emits_created_event_to_moderation() -> None:
    product_id = uuid4()
    seller_id = uuid4()
    FakeProductRepository.product = _product(
        product_id=product_id, seller_id=seller_id
    )

    await SKUService(FakeSession()).create(
        seller_id, SKUCreate(**_payload(product_id=str(product_id)))
    )

    assert len(FakeModerationClient.events) == 1
    event = FakeModerationClient.events[0]
    assert event["event_type"] == "PRODUCT_CREATED"
    assert UUID(event["idempotency_key"])
    assert event["payload"]["product_id"] == str(product_id)
    assert event["payload"]["seller_id"] == str(seller_id)
    assert event["payload"]["json_after"]["status"] == "ON_MODERATION"


@pytest.mark.asyncio
async def test_second_sku_no_state_change() -> None:
    product_id = uuid4()
    seller_id = uuid4()
    existing_sku = SimpleNamespace(id=uuid4(), product_id=product_id)
    FakeProductRepository.product = _product(
        product_id=product_id,
        seller_id=seller_id,
        status=ProductStatus.ON_MODERATION,
        skus=[existing_sku],
    )

    await SKUService(FakeSession()).create(
        seller_id, SKUCreate(**_payload(product_id=str(product_id)))
    )

    assert FakeProductRepository.product.status == ProductStatus.ON_MODERATION
    assert FakeModerationClient.events == []


@pytest.mark.asyncio
async def test_add_sku_to_hard_blocked_returns_403() -> None:
    product_id = uuid4()
    seller_id = uuid4()
    FakeProductRepository.product = _product(
        product_id=product_id,
        seller_id=seller_id,
        status=ProductStatus.HARD_BLOCKED,
    )

    with pytest.raises(Exception) as exc_info:
        await SKUService(FakeSession()).create(
            seller_id, SKUCreate(**_payload(product_id=str(product_id)))
        )

    assert exc_info.value.status_code == 403


class FakeDB:
    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


async def _fake_db():
    yield FakeDB()


async def _fake_seller():
    return SimpleNamespace(id=uuid4(), is_active=True)


def test_missing_image_returns_400() -> None:
    payload = _payload()
    payload.pop("images")

    app.dependency_overrides[skus_router.get_current_seller] = _fake_seller
    app.dependency_overrides[skus_router.get_db] = _fake_db
    try:
        response = TestClient(app).post("/api/v1/skus", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "images" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_duplicate_moderation_event_treated_as_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 409

        def raise_for_status(self) -> None:
            raise AssertionError("duplicate moderation event should not raise")

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: object, headers: dict[str, str]):
            return FakeResponse()

    product = _product(product_id=uuid4(), seller_id=uuid4())
    monkeypatch.setattr(moderation_module.httpx, "AsyncClient", FakeAsyncClient)

    await ModerationClient().send_product_created(product)
