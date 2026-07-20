from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import reservations as reservations_router
from src.main import app
from src.schemas.reservation import ReserveItem, ReserveRequest, UnreserveRequest
from src.services import reservation_service as reservation_service_module
from src.services.reservation_service import ReservationService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _sku(*, stock=10, reserved_quantity=0):
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
    reservations_by_key: dict[str, object] = {}
    reservations_by_order: dict[object, list[object]] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_idempotency_key(self, idempotency_key: str):
        return self.reservations_by_key.get(idempotency_key)

    async def create_batch(self, *, order_id, idempotency_key, items):
        created_at = datetime.now(timezone.utc)
        reservations = [
            SimpleNamespace(
                id=uuid4(),
                order_id=order_id,
                sku_id=item.sku_id,
                quantity=item.quantity,
                idempotency_key=idempotency_key,
                created_at=created_at,
            )
            for item in items
        ]
        self.reservations_by_key[idempotency_key] = reservations[0]
        self.reservations_by_order[order_id] = reservations
        return reservations

    async def list_by_order(self, order_id):
        return list(self.reservations_by_order.get(order_id, []))

    async def delete_many(self, reservations):
        for reservation in reservations:
            self.reservations_by_order[reservation.order_id].remove(reservation)


class FakeB2CClient:
    out_of_stock_events: list[dict[str, object]] = []

    async def send_sku_out_of_stock(self, sku) -> None:
        self.out_of_stock_events.append(
            {
                "event_type": "SKU_OUT_OF_STOCK",
                "payload": {"sku_id": str(sku.id)},
            }
        )


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeSKURepository.skus = {}
    FakeReservationRepository.reservations_by_key = {}
    FakeReservationRepository.reservations_by_order = {}
    FakeB2CClient.out_of_stock_events = []
    monkeypatch.setattr(reservation_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", FakeReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module, "B2CClient", FakeB2CClient, raising=False
    )


def _reserve_request(*items, idempotency_key: str | None = None, order_id=None):
    return ReserveRequest(
        order_id=order_id or uuid4(),
        idempotency_key=idempotency_key or str(uuid4()),
        items=[ReserveItem(sku_id=sku_id, quantity=quantity) for sku_id, quantity in items],
    )


@pytest.mark.asyncio
async def test_reserve_all_skus_succeeds() -> None:
    sku_a = _sku(stock=10, reserved_quantity=1)
    sku_b = _sku(stock=5, reserved_quantity=0)
    FakeSKURepository.skus = {sku_a.id: sku_a, sku_b.id: sku_b}

    response = await ReservationService(FakeSession()).reserve(
        _reserve_request((sku_a.id, 3), (sku_b.id, 2))
    )

    assert response["status"] == "RESERVED"
    assert response["reserved_at"] is not None
    assert sku_a.stock == 10
    assert sku_a.reserved_quantity == 4
    assert sku_b.stock == 5
    assert sku_b.reserved_quantity == 2


@pytest.mark.asyncio
async def test_partial_insufficient_stock_returns_409_all_rollback() -> None:
    sku_a = _sku(stock=10, reserved_quantity=1)
    sku_b = _sku(stock=5, reserved_quantity=4)
    FakeSKURepository.skus = {sku_a.id: sku_a, sku_b.id: sku_b}

    with pytest.raises(Exception) as exc_info:
        await ReservationService(FakeSession()).reserve(
            _reserve_request((sku_a.id, 3), (sku_b.id, 2))
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "INSUFFICIENT_STOCK",
        "message": "Insufficient stock",
    }
    assert sku_a.reserved_quantity == 1
    assert sku_b.reserved_quantity == 4


@pytest.mark.asyncio
async def test_idempotent_reserve_returns_200_without_double_deduction() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    idempotency_key = str(uuid4())
    service = ReservationService(FakeSession())
    request = _reserve_request((sku.id, 3), idempotency_key=idempotency_key)

    first = await service.reserve(request)
    second = await service.reserve(request)

    assert first == second
    assert sku.reserved_quantity == 3


@pytest.mark.asyncio
async def test_idempotent_reserve_returns_original_order_id() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    idempotency_key = str(uuid4())
    original_order_id = uuid4()
    service = ReservationService(FakeSession())

    first = await service.reserve(
        _reserve_request(
            (sku.id, 3),
            idempotency_key=idempotency_key,
            order_id=original_order_id,
        )
    )
    second = await service.reserve(
        _reserve_request((sku.id, 3), idempotency_key=idempotency_key)
    )

    assert first == second
    assert second["order_id"] == original_order_id


@pytest.mark.asyncio
async def test_sku_out_of_stock_event_emitted() -> None:
    sku = _sku(stock=3, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}

    await ReservationService(FakeSession()).reserve(_reserve_request((sku.id, 3)))

    assert FakeB2CClient.out_of_stock_events == [
        {
            "event_type": "SKU_OUT_OF_STOCK",
            "payload": {"sku_id": str(sku.id)},
        }
    ]


@pytest.mark.asyncio
async def test_unreserve_restores_quantities() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    order_id = uuid4()
    service = ReservationService(FakeSession())

    await service.reserve(_reserve_request((sku.id, 3), order_id=order_id))
    response = await service.unreserve(UnreserveRequest(order_id=order_id))

    assert response["status"] == "UNRESERVED"
    assert response["processed_at"] is not None
    assert sku.stock == 10
    assert sku.reserved_quantity == 0


def test_reserve_missing_service_key_returns_401() -> None:
    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[reservations_router.get_db] = fake_db
    try:
        response = TestClient(app).post("/api/v1/reserve", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


async def _fake_db():
    yield FakeSession()


def test_reserve_response_includes_reserved_at() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    order_id = uuid4()

    app.dependency_overrides[reservations_router.get_db] = _fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/inventory/reserve",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "order_id": str(order_id),
                "idempotency_key": str(uuid4()),
                "items": [{"sku_id": str(sku.id), "quantity": 3}],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESERVED"
    assert body["order_id"] == str(order_id)
    assert "reserved_at" in body


def test_unreserve_response_includes_processed_at() -> None:
    order_id = uuid4()

    app.dependency_overrides[reservations_router.get_db] = _fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/inventory/unreserve",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={"order_id": str(order_id)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNRESERVED"
    assert body["order_id"] == str(order_id)
    assert "processed_at" in body


def test_insufficient_stock_response_matches_error_contract() -> None:
    sku = _sku(stock=1, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}

    app.dependency_overrides[reservations_router.get_db] = _fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/inventory/reserve",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "order_id": str(uuid4()),
                "idempotency_key": str(uuid4()),
                "items": [{"sku_id": str(sku.id), "quantity": 2}],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {
        "code": "INSUFFICIENT_STOCK",
        "message": "Insufficient stock",
    }
