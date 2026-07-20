from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import reservations as reservations_router
from src.main import app
from src.schemas.reservation import FulfillRequest
from src.services import reservation_service as reservation_service_module
from src.services.reservation_service import ReservationService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _sku(*, stock=10, reserved_quantity=3):
    return SimpleNamespace(
        id=uuid4(),
        stock=stock,
        reserved_quantity=reserved_quantity,
        is_active=True,
    )


class FakeSKURepository:
    skus: dict[object, object] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_for_update(self, sku_ids):
        return [self.skus[sku_id] for sku_id in sku_ids if sku_id in self.skus]


class FakeReservationRepository:
    reservations_by_order: dict[object, list[object]] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_by_order(self, order_id):
        return list(self.reservations_by_order.get(order_id, []))

    async def delete_many(self, reservations):
        for reservation in reservations:
            self.reservations_by_order[reservation.order_id].remove(reservation)


class FakeFulfilledOrderRepository:
    fulfilled_order_ids: set[object] = set()

    def __init__(self, session: object) -> None:
        self.session = session

    async def exists(self, order_id) -> bool:
        return order_id in self.fulfilled_order_ids

    async def mark_fulfilled(self, order_id) -> None:
        self.fulfilled_order_ids.add(order_id)


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeSKURepository.skus = {}
    FakeReservationRepository.reservations_by_order = {}
    FakeFulfilledOrderRepository.fulfilled_order_ids = set()
    monkeypatch.setattr(reservation_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", FakeReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module,
        "FulfilledOrderRepository",
        FakeFulfilledOrderRepository,
        raising=False,
    )


def _reservation(*, order_id, sku_id, quantity=3):
    return SimpleNamespace(
        id=uuid4(),
        order_id=order_id,
        sku_id=sku_id,
        quantity=quantity,
    )


@pytest.mark.asyncio
async def test_fulfill_decreases_reserved_quantity() -> None:
    order_id = uuid4()
    sku = _sku(stock=10, reserved_quantity=3)
    FakeSKURepository.skus = {sku.id: sku}
    FakeReservationRepository.reservations_by_order = {
        order_id: [_reservation(order_id=order_id, sku_id=sku.id, quantity=3)]
    }

    response = await ReservationService(FakeSession()).fulfill(
        FulfillRequest(order_id=order_id)
    )

    assert response["status"] == "FULFILLED"
    assert response["processed_at"] is not None
    assert sku.reserved_quantity == 0


@pytest.mark.asyncio
async def test_active_quantity_unchanged() -> None:
    order_id = uuid4()
    sku = _sku(stock=10, reserved_quantity=3)
    active_before = sku.stock - sku.reserved_quantity
    FakeSKURepository.skus = {sku.id: sku}
    FakeReservationRepository.reservations_by_order = {
        order_id: [_reservation(order_id=order_id, sku_id=sku.id, quantity=3)]
    }

    await ReservationService(FakeSession()).fulfill(FulfillRequest(order_id=order_id))

    assert sku.stock - sku.reserved_quantity == active_before
    assert sku.stock == 7


@pytest.mark.asyncio
async def test_idempotent_fulfill_no_double_deduction() -> None:
    order_id = uuid4()
    sku = _sku(stock=10, reserved_quantity=3)
    FakeSKURepository.skus = {sku.id: sku}
    FakeReservationRepository.reservations_by_order = {
        order_id: [_reservation(order_id=order_id, sku_id=sku.id, quantity=3)]
    }
    service = ReservationService(FakeSession())

    first = await service.fulfill(FulfillRequest(order_id=order_id))
    second = await service.fulfill(FulfillRequest(order_id=order_id))

    assert first["status"] == second["status"] == "FULFILLED"
    assert first["order_id"] == second["order_id"] == order_id
    assert first["processed_at"] is not None
    assert second["processed_at"] is not None
    assert sku.stock == 7
    assert sku.reserved_quantity == 0


@pytest.mark.asyncio
async def test_empty_fulfill_does_not_block_later_reservation() -> None:
    order_id = uuid4()
    sku = _sku(stock=10, reserved_quantity=3)
    service = ReservationService(FakeSession())

    early = await service.fulfill(FulfillRequest(order_id=order_id))
    FakeSKURepository.skus = {sku.id: sku}
    FakeReservationRepository.reservations_by_order = {
        order_id: [_reservation(order_id=order_id, sku_id=sku.id, quantity=3)]
    }
    later = await service.fulfill(FulfillRequest(order_id=order_id))

    assert early["status"] == later["status"] == "FULFILLED"
    assert early["order_id"] == later["order_id"] == order_id
    assert early["processed_at"] is not None
    assert later["processed_at"] is not None
    assert sku.stock == 7
    assert sku.reserved_quantity == 0


def test_fulfill_routes_include_processed_at() -> None:
    order_id = uuid4()
    sku = _sku(stock=10, reserved_quantity=3)
    FakeSKURepository.skus = {sku.id: sku}
    FakeReservationRepository.reservations_by_order = {
        order_id: [_reservation(order_id=order_id, sku_id=sku.id, quantity=3)]
    }

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[reservations_router.get_db] = fake_db
    try:
        client = TestClient(app)
        first = client.post(
            "/api/v1/fulfill",
            json={"order_id": str(order_id)},
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
        alias = client.post(
            "/api/v1/inventory/fulfill",
            json={"order_id": str(order_id)},
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.json()["processed_at"]
    assert alias.status_code == 200
    assert alias.json()["processed_at"]


def test_fulfill_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[reservations_router.get_db] = fake_db
    try:
        response = TestClient(app).post("/api/v1/fulfill", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
