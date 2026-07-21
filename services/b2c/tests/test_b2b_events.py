from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from src.api.deps import get_db
from src.models.order import OrderStatus
from src.main import app
from src.schemas.b2b_event import ProductEventRequest
from src.services import b2b_event_service as b2b_event_service_module
from src.services.b2b_event_service import B2BEventService


pytestmark = pytest.mark.anyio


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "SKU_OUT_OF_STOCK",
        "idempotency_key": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"sku_id": str(uuid4())},
    }
    event.update(overrides)
    return event


def _product_event(**overrides: object) -> ProductEventRequest:
    payload: dict[str, object] = {
        "event": "PRODUCT_BLOCKED",
        "idempotency_key": uuid4(),
        "product_id": uuid4(),
        "sku_ids": [uuid4(), uuid4()],
        "reason": "Moderation blocked product",
        "date": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return ProductEventRequest.model_validate(payload)


class FakeSession:
    processed_keys: set[object] = set()
    added = []
    rolled_back = False
    committed = False
    fail_on_duplicate = False

    def __init__(self) -> None:
        self.added = []
        self.rolled_back = False
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            key = getattr(obj, "idempotency_key", None)
            if key is None:
                continue
            if key in self.processed_keys:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.processed_keys.add(key)

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True


class FakeCartRepository:
    updates: list[tuple[list[object], str]] = []

    def __init__(self, session) -> None:
        self.session = session

    async def mark_skus_unavailable(self, sku_ids, unavailable_reason: str) -> int:
        self.updates.append((list(sku_ids), unavailable_reason))
        return len(sku_ids)


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeSession.processed_keys = set()
    FakeCartRepository.updates = []
    monkeypatch.setattr(
        b2b_event_service_module,
        "CartRepository",
        FakeCartRepository,
    )
    session = FakeSession()

    async def fake_db():
        yield session

    app.dependency_overrides[get_db] = fake_db
    yield
    app.dependency_overrides.clear()


def test_receive_sku_out_of_stock_event_returns_204() -> None:
    response = TestClient(app).post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=_event(),
    )

    assert response.status_code == 204
    assert response.content == b""


def test_receive_b2b_event_without_service_key_returns_401() -> None:
    response = TestClient(app).post("/api/v1/b2b/events", json=_event())

    assert response.status_code == 401
    assert response.json() == {
        "code": "SERVICE_KEY_INVALID",
        "message": "Invalid or missing service key",
    }


async def test_product_blocked_marks_cart_items_unavailable() -> None:
    sku_ids = [uuid4(), uuid4()]
    event = _product_event(sku_ids=sku_ids)

    processed = await B2BEventService(FakeSession()).handle_product_event(event)

    assert processed is True
    assert FakeCartRepository.updates == [(sku_ids, "PRODUCT_BLOCKED")]


def test_product_blocked_endpoint_accepts_event() -> None:
    sku_ids = [uuid4(), uuid4()]
    event = _product_event(sku_ids=sku_ids).model_dump(mode="json")

    response = TestClient(app).post(
        "/api/v1/events/product",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=event,
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert FakeCartRepository.updates == [(sku_ids, "PRODUCT_BLOCKED")]


async def test_product_deleted_marks_cart_items_unavailable() -> None:
    sku_ids = [uuid4()]
    event = _product_event(event="PRODUCT_DELETED", sku_ids=sku_ids, reason=None)

    processed = await B2BEventService(FakeSession()).handle_product_event(event)

    assert processed is True
    assert FakeCartRepository.updates == [(sku_ids, "PRODUCT_DELETED")]


async def test_sku_out_of_stock_marks_cart_items_out_of_stock() -> None:
    sku_ids = [uuid4()]
    event = _product_event(event="SKU_OUT_OF_STOCK", sku_ids=sku_ids, reason=None)

    processed = await B2BEventService(FakeSession()).handle_product_event(event)

    assert processed is True
    assert FakeCartRepository.updates == [(sku_ids, "OUT_OF_STOCK")]


async def test_orders_not_affected_by_product_blocked() -> None:
    sku_id = uuid4()
    order = SimpleNamespace(
        status=OrderStatus.PAID,
        items=[
            SimpleNamespace(
                sku_id=sku_id,
                unit_price=1000,
                line_total=1000,
            )
        ],
    )
    event = _product_event(sku_ids=[sku_id])

    await B2BEventService(FakeSession()).handle_product_event(event)

    assert order.status == OrderStatus.PAID
    assert order.items[0].unit_price == 1000
    assert order.items[0].line_total == 1000


async def test_idempotent_event_no_side_effects() -> None:
    idempotency_key = uuid4()
    event = _product_event(idempotency_key=idempotency_key)
    first_session = FakeSession()
    second_session = FakeSession()

    first = await B2BEventService(first_session).handle_product_event(event)
    second = await B2BEventService(second_session).handle_product_event(event)

    assert first is True
    assert second is False
    assert second_session.rolled_back is True
    assert FakeCartRepository.updates == [(event.sku_ids, "PRODUCT_BLOCKED")]


def test_missing_service_key_returns_401() -> None:
    event = _product_event().model_dump(mode="json")

    response = TestClient(app).post("/api/v1/events/product", json=event)

    assert response.status_code == 401
    assert response.json() == {
        "code": "SERVICE_KEY_INVALID",
        "message": "Invalid or missing service key",
    }
