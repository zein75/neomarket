from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import moderation_events as moderation_router
from src.main import app
from src.models.product import ProductStatus
from src.schemas.moderation_event import ModerationDecisionEvent
from src.services import product_service as product_service_module
from src.services import moderation_event_service as moderation_service_module
from src.services.moderation_event_service import ModerationEventService
from src.services.product_service import ProductService


class FakeSession:
    async def flush(self) -> None:
        return None


def _product(*, status=ProductStatus.ON_MODERATION):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=uuid4(),
        title="Wireless keyboard",
        description="Low-profile keyboard",
        category_id=uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        blocking_reason={"title": "Old reason"},
        field_reports=[{"field_name": "description", "comment": "Old report"}],
        status=status,
        category=None,
        is_active=False,
        deleted=False,
        skus=[],
    )


class FakeProductRepository:
    product = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_with_skus(self, product_id):
        if self.product and self.product.id == product_id:
            return self.product
        return None


class FakeProcessedEventRepository:
    keys: set[str] = set()

    def __init__(self, session: object) -> None:
        self.session = session

    async def exists(self, idempotency_key: str) -> bool:
        return idempotency_key in self.keys

    async def mark_processed(self, idempotency_key: str) -> None:
        self.keys.add(idempotency_key)


class FakeB2CClient:
    blocked_events: list[dict[str, object]] = []

    async def send_product_blocked(self, product) -> None:
        self.blocked_events.append(
            {
                "event_type": "PRODUCT_BLOCKED",
                "payload": {
                    "product_id": str(product.id),
                    "status": product.status,
                },
            }
        )


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.product = None
    FakeProcessedEventRepository.keys = set()
    FakeB2CClient.blocked_events = []
    monkeypatch.setattr(
        moderation_service_module, "ProductRepository", FakeProductRepository
    )
    monkeypatch.setattr(product_service_module, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(
        moderation_service_module,
        "ProcessedEventRepository",
        FakeProcessedEventRepository,
    )
    monkeypatch.setattr(
        moderation_service_module, "B2CClient", FakeB2CClient, raising=False
    )


def _event(product_id, *, decision: str, hard_block: bool = False, key: str | None = None):
    return ModerationDecisionEvent(
        idempotency_key=key or str(uuid4()),
        event_type="PRODUCT_MODERATION_DECIDED",
        product_id=product_id,
        decision=decision,
        hard_block=hard_block,
        blocking_reason={
            "id": str(uuid4()),
            "title": "Bad content",
            "comment": "Fix content",
        },
        field_reports=[
            {
                "field_name": "images[0]",
                "sku_id": None,
                "comment": "Image is blurry",
            }
        ],
    )


@pytest.mark.asyncio
async def test_moderated_event_clears_blocking_data() -> None:
    product = _product()
    FakeProductRepository.product = product

    response = await ModerationEventService(FakeSession()).apply(
        _event(product.id, decision="MODERATED")
    )

    assert response == {"status": "APPLIED"}
    assert product.status == ProductStatus.MODERATED
    assert product.is_active is True
    assert product.blocking_reason is None
    assert product.field_reports == []


@pytest.mark.asyncio
async def test_blocked_soft_saves_field_reports() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, decision="BLOCKED", hard_block=False)
    )

    assert product.status == ProductStatus.BLOCKED
    assert product.is_active is False
    assert product.blocking_reason["title"] == "Bad content"
    assert product.field_reports[0]["field_name"] == "images[0]"
    assert len(FakeB2CClient.blocked_events) == 1


@pytest.mark.asyncio
async def test_blocked_hard_sets_terminal_status() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, decision="BLOCKED", hard_block=True)
    )

    assert product.status == ProductStatus.HARD_BLOCKED
    assert len(FakeB2CClient.blocked_events) == 1


@pytest.mark.asyncio
async def test_hard_blocked_product_rejects_seller_edits() -> None:
    product = _product(status=ProductStatus.HARD_BLOCKED)
    FakeProductRepository.product = product

    with pytest.raises(Exception) as exc_info:
        await ProductService(FakeSession()).delete(product.id, product.seller_id)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_event_same_idempotency_key_no_side_effects() -> None:
    product = _product()
    FakeProductRepository.product = product
    service = ModerationEventService(FakeSession())
    key = str(uuid4())

    first = await service.apply(_event(product.id, decision="BLOCKED", key=key))
    product.status = ProductStatus.ON_MODERATION
    product.blocking_reason = None
    product.field_reports = []
    second = await service.apply(_event(product.id, decision="BLOCKED", key=key))

    assert first == {"status": "APPLIED"}
    assert second == {"status": "DUPLICATE"}
    assert product.status == ProductStatus.ON_MODERATION
    assert FakeB2CClient.blocked_events == [
        {
            "event_type": "PRODUCT_BLOCKED",
            "payload": {"product_id": str(product.id), "status": "BLOCKED"},
        }
    ]


def test_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post("/api/v1/events/moderation", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
