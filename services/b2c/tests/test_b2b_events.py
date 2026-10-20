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
    processed_records: dict[object, object] = {}
    added = []
    rolled_back = False
    committed = False
    fail_on_duplicate = False

    def __init__(self) -> None:
        self.added = []
        self.rolled_back = False
        self.committed = False

    async def execute(self, statement) -> None:
        self.executed_statement = statement

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
            self.processed_records[key] = obj

    async def get(self, _model, key):
        return self.processed_records.get(key)

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture(autouse=True)
def patch_dependencies():
    FakeSession.processed_keys = set()
    FakeSession.processed_records = {}
    session = FakeSession()

    async def fake_db():
        yield session

    app.state.test_session = session
    app.dependency_overrides[get_db] = fake_db
    yield
    app.dependency_overrides.clear()


def test_receive_sku_out_of_stock_event_returns_202() -> None:
    response = TestClient(app).post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=_event(),
    )

    assert response.status_code == 202
    assert response.content == b""


def test_b2b_event_openapi_exposes_only_the_canonical_receiver() -> None:
    """The compatibility adapter must not replace the frozen wire contract."""
    paths = app.openapi()["paths"]
    assert "/api/v1/b2b/events" in paths
    assert paths["/api/v1/b2b/events"]["post"]["responses"].get("202")
    assert "/api/v1/events/product" not in paths


def test_receive_b2b_event_without_service_key_returns_401() -> None:
    response = TestClient(app).post("/api/v1/b2b/events", json=_event())

    assert response.status_code == 401
    assert response.json() == {
        "code": "SERVICE_KEY_INVALID",
        "message": "Invalid or missing service key",
    }


def test_catalog_envelope_is_durably_accepted() -> None:
    event = {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": "product.deleted",
        "producer": "b2b",
        "aggregate_type": "product",
        "aggregate_id": str(uuid4()),
        "aggregate_version": 2,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(uuid4()),
        "payload": {"product_id": str(uuid4()), "deleted": True},
    }
    response = TestClient(app).post(
        "/internal/v1/events/catalog",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=event,
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}


def test_catalog_safety_hold_event_is_durably_accepted() -> None:
    event_id = uuid4()
    product_id = uuid4()
    event = {
        "schema_version": 1,
        "event_id": str(event_id),
        "event_type": "product.safety_hold.v1",
        "producer": "b2b",
        "aggregate_type": "product",
        "aggregate_id": str(product_id),
        "aggregate_version": 4,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(uuid4()),
        "causation_id": str(uuid4()),
        "payload": {
            "product_id": str(product_id),
            "revision": 4,
            "expires_at": (datetime.now(timezone.utc).replace(microsecond=0)).isoformat(),
            "reason_code": "RISK_REVIEW",
        },
    }

    response = TestClient(app).post(
        "/internal/v1/events/catalog",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=event,
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert any(getattr(item, "event", None) == "product.safety_hold.v1" for item in app.state.test_session.added)


def test_catalog_envelope_rejects_wrong_producer() -> None:
    event = {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": "product.deleted",
        "producer": "admin",
        "aggregate_type": "product",
        "aggregate_id": str(uuid4()),
        "aggregate_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(uuid4()),
        "payload": {},
    }
    response = TestClient(app).post(
        "/internal/v1/events/catalog",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=event,
    )

    assert response.status_code == 400


def _brand_merge_event(**overrides: object) -> dict[str, object]:
    source_id, target_id = uuid4(), uuid4()
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": "brand.merged.v1",
        "producer": "b2b",
        "aggregate_type": "brand",
        "aggregate_id": str(source_id),
        "aggregate_version": 2,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(uuid4()),
        "causation_id": str(uuid4()),
        "payload": {
            "source_brand_id": str(source_id),
            "target_brand_id": str(target_id),
            "source_version": 2,
            "target_version": 4,
            "taxonomy_version": 12,
            "product_references_moved": 3,
            "impact_hash": "a" * 64,
        },
    }
    event.update(overrides)
    return event


def test_brand_merge_event_is_accepted_by_taxonomy_inbox() -> None:
    response = TestClient(app).post(
        "/internal/v1/events/taxonomy",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=_brand_merge_event(),
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert app.state.test_session.added[-1].event == "brand.merged.v1"


def test_brand_merge_event_requires_service_authentication() -> None:
    response = TestClient(app).post(
        "/internal/v1/events/taxonomy", json=_brand_merge_event()
    )

    assert response.status_code == 401


def test_brand_merge_event_rejects_inconsistent_source_version() -> None:
    event = _brand_merge_event()
    event["aggregate_version"] = 3
    response = TestClient(app).post(
        "/internal/v1/events/taxonomy",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=event,
    )

    assert response.status_code == 400


def test_brand_merge_event_replay_is_idempotent_and_conflicting_replay_rejected() -> None:
    event = _brand_merge_event()
    headers = {"X-Service-Key": "dev-service-key-change-in-production"}
    with TestClient(app) as client:
        accepted = client.post("/internal/v1/events/taxonomy", headers=headers, json=event)
        replay = client.post("/internal/v1/events/taxonomy", headers=headers, json=event)
        conflicting = client.post(
            "/internal/v1/events/taxonomy",
            headers=headers,
            json={**event, "payload": {**event["payload"], "target_version": 5}},
        )

    assert accepted.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == {"accepted": False}
    assert conflicting.status_code == 409


async def test_product_blocked_does_not_persist_cart_availability() -> None:
    sku_ids = [uuid4(), uuid4()]
    event = _product_event(sku_ids=sku_ids)

    session = FakeSession()
    processed = await B2BEventService(session).handle_product_event(event)

    assert processed is True
    assert not hasattr(session, "executed_statement")


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


async def test_product_deleted_marks_cart_items_unavailable() -> None:
    sku_ids = [uuid4()]
    event = _product_event(event="PRODUCT_DELETED", sku_ids=sku_ids, reason=None)

    processed = await B2BEventService(FakeSession()).handle_product_event(event)

    assert processed is True


async def test_sku_out_of_stock_marks_cart_items_out_of_stock() -> None:
    sku_ids = [uuid4()]
    event = _product_event(event="SKU_OUT_OF_STOCK", sku_ids=sku_ids, reason=None)

    processed = await B2BEventService(FakeSession()).handle_product_event(event)

    assert processed is True


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


def test_missing_service_key_returns_401() -> None:
    event = _product_event().model_dump(mode="json")

    response = TestClient(app).post("/api/v1/events/product", json=event)

    assert response.status_code == 401
    assert response.json() == {
        "code": "SERVICE_KEY_INVALID",
        "message": "Invalid or missing service key",
    }
