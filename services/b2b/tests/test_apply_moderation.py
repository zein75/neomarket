from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.api.routers import moderation_events as moderation_router
from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.schemas.moderation_event import BlockingReason, ModerationDecisionEvent
from src.services import product_service as product_service_module
from src.services import moderation_event_service as moderation_service_module
from src.services.moderation_event_service import ModerationEventService
from src.services.product_service import ProductService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
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
        blocking_reason={
            "id": str(uuid4()),
            "title": "Old reason",
            "comment": "Old comment",
        },
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


class FakeOutboxEventRepository:
    events: list[dict[str, object]] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def create_b2c_event(self, **event: object) -> object:
        self.events.append(event)
        return event


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.product = None
    FakeProcessedEventRepository.keys = set()
    FakeOutboxEventRepository.events = []
    monkeypatch.setattr(
        moderation_service_module, "ProductRepository", FakeProductRepository
    )
    monkeypatch.setattr(product_service_module, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(
        moderation_service_module,
        "ProcessedEventRepository",
        FakeProcessedEventRepository,
    )
    monkeypatch.setattr(moderation_service_module, "OutboxEventRepository", FakeOutboxEventRepository)


def _event(
    product_id,
    *,
    status: str,
    hard_block: bool = False,
    key: str | None = None,
    blocking_reason_id=None,
):
    kwargs = {}
    if status == "BLOCKED":
        kwargs = {
            "hard_block": hard_block,
            "blocking_reason": BlockingReason(
            id=blocking_reason_id or uuid4(),
            title="Moderation block",
            comment="Image is blurry",
            ),
            "field_reports": [
            {
                "field_name": "product_images",
                "sku_id": None,
                "comment": "Image is blurry",
            }
            ],
        }
    return ModerationDecisionEvent(
        idempotency_key=key or str(uuid4()),
        product_id=product_id,
        status=status,
        occurred_at="2026-09-18T12:00:00Z",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_moderated_event_clears_blocking_data() -> None:
    product = _product()
    FakeProductRepository.product = product

    response = await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="MODERATED")
    )

    assert response == {"status": "APPLIED"}
    assert product.status == ProductStatus.MODERATED
    assert product.is_active is True
    assert product.blocking_reason is None
    assert product.field_reports == []


@pytest.mark.asyncio
async def test_unknown_product_returns_declared_bad_request() -> None:
    with pytest.raises(Exception) as exc_info:
        await ModerationEventService(FakeSession()).apply(
            _event(uuid4(), status="MODERATED")
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_blocked_soft_saves_field_reports() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", hard_block=False)
    )

    assert product.status == ProductStatus.BLOCKED
    assert product.is_active is False
    assert product.blocking_reason["id"]
    assert product.field_reports[0]["field_name"] == "product_images"
    assert len(FakeOutboxEventRepository.events) == 1


def test_soft_block_accepts_protocol_field_path_and_default_hard_block(monkeypatch) -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    async def fake_reason(_client, reason_id: str):
        return {"id": reason_id, "title": "Image is blurry", "comment": "Image is blurry"}

    monkeypatch.setattr(moderation_router.ModerationClient, "get_blocking_reason", fake_reason)

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/events/moderation",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "blocking_reason_id": str(uuid4()),
                "field_reports": [
                    {
                        "field_name": "images[0]",
                        "comment": "Image is blurry",
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert product.status == ProductStatus.BLOCKED
    assert product.field_reports[0]["field_name"] == "images[0]"


def test_blocked_without_reason_is_rejected_by_contract_validator() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/moderation/events",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert product.status == ProductStatus.ON_MODERATION


@pytest.mark.asyncio
async def test_blocked_event_saves_blocking_reason_id() -> None:
    product = _product()
    reason_id = uuid4()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", blocking_reason_id=reason_id)
    )

    assert product.blocking_reason == {
        "id": str(reason_id),
        "title": "Moderation block",
        "comment": "Image is blurry",
    }


def test_blocked_event_then_seller_view_returns_blocking_reason(monkeypatch) -> None:
    product = _product()
    reason_id = uuid4()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    async def fake_seller():
        return SimpleNamespace(id=product.seller_id, is_active=True)

    async def fake_reason(_client, reason_id: str):
        return {"id": reason_id, "title": "Image is blurry", "comment": "Image is blurry"}

    monkeypatch.setattr(moderation_router.ModerationClient, "get_blocking_reason", fake_reason)

    app.dependency_overrides[moderation_router.get_db] = fake_db
    app.dependency_overrides[products_router.get_db] = fake_db
    app.dependency_overrides[products_router.get_seller_or_service] = fake_seller
    try:
        event_response = TestClient(app).post(
            "/api/v1/moderation/events",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "hard_block": False,
                "blocking_reason_id": str(reason_id),
                "moderator_comment": "Image is blurry",
                "field_reports": [
                    {
                "field_name": "product_images",
                        "sku_id": None,
                        "comment": "Image is blurry",
                    }
                ],
            },
        )
        product_response = TestClient(app).get(f"/api/v1/products/{product.id}")
    finally:
        app.dependency_overrides.clear()

    assert event_response.status_code == 204
    assert product_response.status_code == 200
    body = product_response.json()
    assert body["status"] == "BLOCKED"
    assert body["blocking_reason"] == {
        "id": str(reason_id),
        "title": "Image is blurry",
        "comment": "Image is blurry",
    }
    assert body["field_reports"] == [
        {
            "field_name": "product_images",
            "sku_id": None,
            "comment": "Image is blurry",
        }
    ]


def test_blocked_event_saves_full_top_level_blocking_reason_for_seller_view(monkeypatch) -> None:
    product = _product()
    reason_id = uuid4()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    async def fake_seller():
        return SimpleNamespace(id=product.seller_id, is_active=True)

    async def fake_reason(_client, reason_id: str):
        return {
            "id": reason_id,
            "title": "Description mismatch",
            "comment": "Photos and description contradict each other",
        }

    monkeypatch.setattr(moderation_router.ModerationClient, "get_blocking_reason", fake_reason)

    app.dependency_overrides[moderation_router.get_db] = fake_db
    app.dependency_overrides[products_router.get_db] = fake_db
    app.dependency_overrides[products_router.get_seller_or_service] = fake_seller
    try:
        event_response = TestClient(app).post(
            "/api/v1/events/moderation",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "hard_block": False,
                "blocking_reason_id": str(reason_id),
                "moderator_comment": "Photos and description contradict each other",
                "field_reports": [
                    {
                        "field_name": "description",
                        "sku_id": None,
                        "comment": "Description copied from another product",
                    }
                ],
            },
        )
        product_response = TestClient(app).get(f"/api/v1/products/{product.id}")
    finally:
        app.dependency_overrides.clear()

    assert event_response.status_code == 204
    assert product_response.status_code == 200
    body = product_response.json()
    assert body["blocking_reason"] == {
        "id": str(reason_id),
        "title": "Description mismatch",
        "comment": "Photos and description contradict each other",
    }
    assert body["moderator_comment"] == "Photos and description contradict each other"


@pytest.mark.asyncio
async def test_blocked_hard_sets_terminal_status() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", hard_block=True)
    )

    assert product.status == ProductStatus.HARD_BLOCKED
    assert len(FakeOutboxEventRepository.events) == 1
    assert FakeOutboxEventRepository.events[0]["event_type"] == "PRODUCT_BLOCKED"


@pytest.mark.asyncio
async def test_soft_block_emits_product_blocked() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", hard_block=False)
    )

    assert product.status == ProductStatus.BLOCKED
    assert FakeOutboxEventRepository.events[0]["event_type"] == "PRODUCT_BLOCKED"


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

    first = await service.apply(_event(product.id, status="BLOCKED", key=key))
    product.status = ProductStatus.ON_MODERATION
    product.blocking_reason = None
    product.field_reports = []
    second = await service.apply(_event(product.id, status="BLOCKED", key=key))

    assert first == {"status": "APPLIED"}
    assert second == {"status": "DUPLICATE"}
    assert product.status == ProductStatus.ON_MODERATION
    assert len(FakeOutboxEventRepository.events) == 1
    assert FakeOutboxEventRepository.events[0]["idempotency_key"] == key


@pytest.mark.asyncio
async def test_new_block_decision_has_a_distinct_b2c_idempotency_key() -> None:
    product = _product()
    FakeProductRepository.product = product

    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", key=str(uuid4()))
    )
    await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED", key=str(uuid4()))
    )

    assert len(FakeOutboxEventRepository.events) == 2
    assert len({event["idempotency_key"] for event in FakeOutboxEventRepository.events}) == 2


@pytest.mark.asyncio
async def test_parallel_duplicate_event_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RaceProcessedEventRepository(FakeProcessedEventRepository):
        async def exists(self, idempotency_key: str) -> bool:
            return False

        async def mark_processed(self, idempotency_key: str) -> None:
            raise IntegrityError("duplicate key", params=None, orig=None)

    product = _product()
    FakeProductRepository.product = product
    monkeypatch.setattr(
        moderation_service_module,
        "ProcessedEventRepository",
        RaceProcessedEventRepository,
    )

    response = await ModerationEventService(FakeSession()).apply(
        _event(product.id, status="BLOCKED")
    )

    assert response == {"status": "DUPLICATE"}
    assert product.status == ProductStatus.ON_MODERATION
    assert FakeOutboxEventRepository.events == []


def test_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post("/api/v1/events/moderation", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_moderation_event_route_returns_204() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/events/moderation",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "MODERATED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""


def test_moderation_event_route_rejects_internal_status_field() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/events/moderation",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "status": "MODERATED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert product.status == ProductStatus.ON_MODERATION


def test_moderation_event_route_rejects_undeclared_blocking_reason_snapshot() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/moderation/events",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "blocking_reason_id": str(uuid4()),
                "blocking_reason": {
                    "id": str(uuid4()),
                    "title": "Must not be accepted",
                    "comment": "Undeclared wire field",
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert product.status == ProductStatus.ON_MODERATION


def test_moderation_event_route_rejects_undeclared_field_report_fields() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/events/moderation",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "hard_block": False,
                "blocking_reason_id": str(uuid4()),
                "moderator_comment": "Invalid field report shape",
                "field_reports": [
                    {
                        "field_name": "description",
                        "sku_id": None,
                        "comment": "Invalid",
                        "unexpected": "must be rejected",
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert product.status == ProductStatus.ON_MODERATION


def test_moderation_event_alias_returns_204() -> None:
    product = _product()
    FakeProductRepository.product = product

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/moderation/events",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "MODERATED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""


def test_reason_lookup_failure_uses_declared_moderation_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frozen endpoint has no 503 response, so do not emit one."""
    product = _product()
    FakeProductRepository.product = product

    async def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("moderation down")

    async def fake_db():
        yield FakeSession()

    monkeypatch.setattr(
        moderation_router.ModerationClient,
        "get_blocking_reason",
        unavailable,
    )
    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/moderation/events",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "idempotency_key": str(uuid4()),
                "event_type": "BLOCKED",
                "product_id": str(product.id),
                "occurred_at": "2026-09-18T12:00:00Z",
                "blocking_reason_id": str(uuid4()),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {
        "code": "BLOCKING_REASON_LOOKUP_FAILED",
        "message": "Blocking reason could not be resolved",
    }
