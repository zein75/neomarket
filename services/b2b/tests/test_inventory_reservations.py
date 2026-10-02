from datetime import datetime, timezone
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.routers import reservations as reservations_router
from src.main import app
from src.models import Base
from src.models.product import Product
from src.models.product import ProductStatus
from src.models.reservation import Reservation
from src.models.reservation_operation import ReservationOperation
from src.models.outbox_event import OutboxEvent
from src.models.seller import Seller
from src.models.sku import SKU
from src.repositories.reservation_operation_repo import (
    ReservationOperationRepository,
)
from src.repositories.reservation_repo import ReservationRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.reservation import ReserveItem, ReserveRequest, UnreserveRequest
from src.services import reservation_service as reservation_service_module
from src.services.reservation_service import ReservationService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class SyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, instance) -> None:
        self._session.add(instance)

    def add_all(self, instances) -> None:
        self._session.add_all(instances)

    async def execute(self, statement):
        return self._session.execute(statement)

    async def flush(self) -> None:
        self._session.flush()

    async def refresh(self, instance) -> None:
        self._session.refresh(instance)

    async def delete(self, instance) -> None:
        self._session.delete(instance)


def _sku(*, stock=10, reserved_quantity=0):
    product_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        product=SimpleNamespace(id=product_id, status=ProductStatus.MODERATED),
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
        self.reservations_by_order[order_id] = reservations
        return reservations

    async def list_by_order(self, order_id):
        return list(self.reservations_by_order.get(order_id, []))

    async def delete_many(self, reservations):
        for reservation in reservations:
            self.reservations_by_order[reservation.order_id].remove(reservation)


class FakeReservationOperationRepository:
    operations_by_key: dict[str, object] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_idempotency_key(self, idempotency_key: str):
        return self.operations_by_key.get(idempotency_key)

    async def create(self, *, idempotency_key: str, order_id, request_hash, response=None):
        operation = SimpleNamespace(
            idempotency_key=idempotency_key,
            order_id=order_id,
            created_at=datetime.now(timezone.utc),
            request_hash=request_hash,
            response=response,
        )
        self.operations_by_key[idempotency_key] = operation
        return operation


class FakeB2CClient:
    out_of_stock_events: list[dict[str, object]] = []
    fail_delivery = False

    async def send_sku_out_of_stock(self, sku) -> None:
        if self.fail_delivery:
            raise RuntimeError("B2C unavailable")
        self.out_of_stock_events.append(
            {
                "event_type": "SKU_OUT_OF_STOCK",
                "payload": {"sku_id": str(sku.id)},
            }
        )

    async def send_outbox_event(self, payload) -> None:
        if self.fail_delivery:
            raise RuntimeError("B2C unavailable")
        self.out_of_stock_events.append(payload)


class FakeOutboxRepository:
    def __init__(self, session: FakeSession, event: object) -> None:
        self.session = session
        self.event = event

    async def list_pending(self, limit: int = 100) -> list[object]:
        return [self.event]


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeSKURepository.skus = {}
    FakeReservationRepository.reservations_by_order = {}
    FakeReservationOperationRepository.operations_by_key = {}
    FakeB2CClient.out_of_stock_events = []
    FakeB2CClient.fail_delivery = False
    monkeypatch.setattr(reservation_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", FakeReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        FakeReservationOperationRepository,
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


def _sync_postgres_url(database_url: str) -> str:
    """Adapt the async application URL for this deliberately synchronous test harness."""
    return database_url.replace("+asyncpg", "+psycopg2", 1)


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
    assert exc_info.value.detail["code"] == "INSUFFICIENT_STOCK"
    assert exc_info.value.detail["details"]["failed_items"][0]["available"] == 1
    assert sku_a.reserved_quantity == 1
    assert sku_b.reserved_quantity == 4


@pytest.mark.asyncio
async def test_reserve_same_key_different_payload_returns_conflict_without_mutation() -> None:
    sku = _sku(stock=10)
    FakeSKURepository.skus = {sku.id: sku}
    key = str(uuid4())
    order_id = uuid4()
    service = ReservationService(FakeSession())

    await service.reserve(
        _reserve_request((sku.id, 2), idempotency_key=key, order_id=order_id)
    )
    with pytest.raises(Exception) as exc_info:
        await service.reserve(
            _reserve_request((sku.id, 3), idempotency_key=key, order_id=order_id)
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
    assert sku.reserved_quantity == 2


@pytest.mark.asyncio
async def test_unmoderated_product_cannot_be_reserved() -> None:
    sku = _sku(stock=3, reserved_quantity=0)
    sku.product.status = ProductStatus.ON_MODERATION
    FakeSKURepository.skus = {sku.id: sku}

    with pytest.raises(Exception) as exc_info:
        await ReservationService(FakeSession()).reserve(_reserve_request((sku.id, 1)))

    assert exc_info.value.status_code == 409
    assert sku.reserved_quantity == 0
    assert exc_info.value.detail["details"]["failed_items"][0]["reason"] == "PRODUCT_BLOCKED"


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
        _reserve_request(
            (sku.id, 3),
            idempotency_key=idempotency_key,
            order_id=original_order_id,
        )
    )

    assert first == second
    assert second["order_id"] == original_order_id


@pytest.mark.asyncio
async def test_idempotent_reserve_returns_original_remaining_stock_after_new_operation() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    key = str(uuid4())
    service = ReservationService(FakeSession())

    order_id = uuid4()
    first = await service.reserve(
        _reserve_request((sku.id, 3), idempotency_key=key, order_id=order_id)
    )
    await service.reserve(_reserve_request((sku.id, 2)))
    repeated = await service.reserve(
        _reserve_request((sku.id, 3), idempotency_key=key, order_id=order_id)
    )

    assert repeated == first
    assert repeated["items"][0]["remaining_stock"] == 7


@pytest.mark.asyncio
async def test_persisted_idempotent_response_survives_a_later_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", ReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        ReservationOperationRepository,
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    seller_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
    first_key = str(uuid4())

    with Session(engine) as session:
        session.add(
            Seller(
                id=seller_id,
                email="seller@example.test",
                hashed_password="hash",
                company_name="Seller",
            )
        )
        session.add(
            Product(
                id=product_id,
                seller_id=seller_id,
                title="Phone",
                description="Last phone",
                category="electronics",
                status=ProductStatus.MODERATED,
            )
        )
        session.add(
            SKU(
                id=sku_id,
                product_id=product_id,
                name="Phone",
                price=100,
                stock=10,
                reserved_quantity=0,
                images=[],
            )
        )
        session.commit()

        adapter = SyncSessionAdapter(session)
        first_request = _reserve_request((sku_id, 3), idempotency_key=first_key)
        first = await ReservationService(adapter).reserve(first_request)
        session.commit()
        session.expire_all()

        await ReservationService(adapter).reserve(_reserve_request((sku_id, 2)))
        session.commit()
        session.expire_all()

        repeated = await ReservationService(adapter).reserve(first_request)
        assert repeated == first
        assert repeated["items"][0]["remaining_stock"] == 7

    Base.metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_postgres_multi_sku_reserve_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise real PostgreSQL uniqueness and row locking, not the fake repository."""
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")

    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", ReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        ReservationOperationRepository,
    )
    engine = create_engine(_sync_postgres_url(database_url))
    seller_id, product_id = uuid4(), uuid4()
    sku_ids = [uuid4(), uuid4(), uuid4()]
    order_id, key = uuid4(), str(uuid4())

    with Session(engine) as session:
        session.query(Reservation).delete()
        session.query(ReservationOperation).delete()
        session.query(SKU).delete()
        session.query(Product).delete()
        session.query(Seller).delete()
        session.add(Seller(id=seller_id, email=f"{seller_id}@test", hashed_password="h", company_name="Seller"))
        session.add(Product(id=product_id, seller_id=seller_id, title="Phone", description="Phone", category="electronics", status=ProductStatus.MODERATED))
        session.add_all([SKU(id=sku_id, product_id=product_id, name=f"SKU-{index}", price=100, stock=5, reserved_quantity=0, images=[]) for index, sku_id in enumerate(sku_ids)])
        session.commit()

        adapter = SyncSessionAdapter(session)
        request = _reserve_request(
            *((sku_id, 1) for sku_id in sku_ids),
            idempotency_key=key,
            order_id=order_id,
        )
        first = await ReservationService(adapter).reserve(request)
        session.commit()
        second = await ReservationService(adapter).reserve(request)
        session.commit()

        assert second == first
        assert session.query(Reservation).filter_by(order_id=order_id).count() == 3
        assert [sku.reserved_quantity for sku in session.query(SKU).order_by(SKU.id)] == [1, 1, 1]


@pytest.mark.asyncio
async def test_postgres_same_key_different_payload_returns_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")

    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(reservation_service_module, "ReservationRepository", ReservationRepository)
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        ReservationOperationRepository,
    )
    engine = create_engine(_sync_postgres_url(database_url))
    seller_id, product_id, sku_id, order_id = uuid4(), uuid4(), uuid4(), uuid4()
    key = str(uuid4())

    with Session(engine) as session:
        session.query(Reservation).delete()
        session.query(ReservationOperation).delete()
        session.query(SKU).delete()
        session.query(Product).delete()
        session.query(Seller).delete()
        session.add(Seller(id=seller_id, email=f"{seller_id}@test", hashed_password="h", company_name="Seller"))
        session.add(Product(id=product_id, seller_id=seller_id, title="Phone", description="Phone", category="electronics", status=ProductStatus.MODERATED))
        session.add(SKU(id=sku_id, product_id=product_id, name="SKU", price=100, stock=5, reserved_quantity=0, images=[]))
        session.commit()

        service = ReservationService(SyncSessionAdapter(session))
        await service.reserve(_reserve_request((sku_id, 2), idempotency_key=key, order_id=order_id))
        session.commit()
        with pytest.raises(Exception) as exc_info:
            await service.reserve(_reserve_request((sku_id, 3), idempotency_key=key, order_id=order_id))

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
        assert session.get(SKU, sku_id).reserved_quantity == 2


@pytest.mark.asyncio
async def test_postgres_concurrent_same_key_reserves_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")
    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(reservation_service_module, "ReservationRepository", ReservationRepository)
    monkeypatch.setattr(reservation_service_module, "ReservationOperationRepository", ReservationOperationRepository)
    engine = create_engine(_sync_postgres_url(database_url))
    seller_id, product_id, sku_id, order_id = uuid4(), uuid4(), uuid4(), uuid4()
    request = _reserve_request((sku_id, 2), idempotency_key=str(uuid4()), order_id=order_id)

    with Session(engine) as session:
        session.query(Reservation).delete()
        session.query(ReservationOperation).delete()
        session.query(SKU).delete()
        session.query(Product).delete()
        session.query(Seller).delete()
        session.add(Seller(id=seller_id, email=f"{seller_id}@test", hashed_password="h", company_name="Seller"))
        session.add(Product(id=product_id, seller_id=seller_id, title="Phone", description="Phone", category="electronics", status=ProductStatus.MODERATED))
        session.add(SKU(id=sku_id, product_id=product_id, name="SKU", price=100, stock=5, reserved_quantity=0, images=[]))
        session.commit()

    def reserve_once() -> dict[str, object]:
        with Session(engine) as session:
            result = asyncio.run(ReservationService(SyncSessionAdapter(session)).reserve(request))
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: reserve_once(), range(2)))

    with Session(engine) as session:
        assert first == second
        assert session.query(Reservation).filter_by(order_id=order_id).count() == 1
        assert session.get(SKU, sku_id).reserved_quantity == 2


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
async def test_sku_out_of_stock_delivery_failure_does_not_rollback_reservation() -> None:
    sku = _sku(stock=3, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    FakeB2CClient.fail_delivery = True

    response = await ReservationService(FakeSession()).reserve(
        _reserve_request((sku.id, 3))
    )

    assert response["status"] == "RESERVED"
    assert sku.reserved_quantity == 3


@pytest.mark.asyncio
async def test_saved_outbox_event_retries_after_b2c_recovers() -> None:
    event = SimpleNamespace(
        destination="B2C",
        status="PENDING",
        attempts=0,
        payload={
            "event_type": "SKU_OUT_OF_STOCK",
            "idempotency_key": str(uuid4()),
            "occurred_at": "2026-10-01T00:00:00+00:00",
            "payload": {"sku_id": str(uuid4()), "product_id": str(uuid4())},
        },
    )
    service = ReservationService(FakeSession())
    service.outbox_repo = FakeOutboxRepository(service.outbox_repo.session, event)
    FakeB2CClient.fail_delivery = True

    assert await service.retry_pending_outbox() == 0
    assert event.status == "PENDING"
    assert event.attempts == 1

    FakeB2CClient.fail_delivery = False
    assert await service.retry_pending_outbox() == 1
    assert event.status == "SENT"
    assert event.attempts == 2


@pytest.mark.asyncio
async def test_persisted_outbox_event_retries_after_b2c_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(
        reservation_service_module, "ReservationRepository", ReservationRepository
    )
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        ReservationOperationRepository,
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    seller_id, product_id, sku_id = uuid4(), uuid4(), uuid4()

    with Session(engine) as session:
        session.add(
            Seller(
                id=seller_id,
                email="seller@example.test",
                hashed_password="hash",
                company_name="Seller",
            )
        )
        session.add(
            Product(
                id=product_id,
                seller_id=seller_id,
                title="Phone",
                description="Last phone",
                category="electronics",
                status=ProductStatus.MODERATED,
            )
        )
        session.add(
            SKU(
                id=sku_id,
                product_id=product_id,
                name="Phone",
                price=100,
                stock=1,
                reserved_quantity=0,
                images=[],
            )
        )
        session.commit()
        adapter = SyncSessionAdapter(session)

        await ReservationService(adapter).reserve(_reserve_request((sku_id, 1)))
        session.commit()
        assert session.query(OutboxEvent).one().status == "PENDING"

        FakeB2CClient.fail_delivery = True
        assert await ReservationService(adapter).retry_pending_outbox() == 0
        session.commit()
        session.expire_all()
        event = session.query(OutboxEvent).one()
        assert event.status == "PENDING"
        assert event.attempts == 1

        FakeB2CClient.fail_delivery = False
        assert await ReservationService(adapter).retry_pending_outbox() == 1
        session.commit()
        session.expire_all()
        event = session.query(OutboxEvent).one()
        assert event.status == "SENT"
        assert event.attempts == 2
        assert FakeB2CClient.out_of_stock_events == [event.payload]

    Base.metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_unreserve_restores_quantities() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    order_id = uuid4()
    service = ReservationService(FakeSession())

    await service.reserve(_reserve_request((sku.id, 3), order_id=order_id))
    response = await service.unreserve(
        UnreserveRequest(
            order_id=order_id,
            items=[ReserveItem(sku_id=sku.id, quantity=3)],
        )
    )

    assert response["status"] == "UNRESERVED"
    assert response["processed_at"] is not None
    assert sku.stock == 10
    assert sku.reserved_quantity == 0


@pytest.mark.asyncio
async def test_unreserve_more_than_reserved_returns_409_without_changes() -> None:
    sku = _sku(stock=10, reserved_quantity=0)
    FakeSKURepository.skus = {sku.id: sku}
    order_id = uuid4()
    service = ReservationService(FakeSession())

    await service.reserve(_reserve_request((sku.id, 3), order_id=order_id))

    with pytest.raises(Exception) as exc_info:
        await service.unreserve(
            UnreserveRequest(
                order_id=order_id,
                items=[ReserveItem(sku_id=sku.id, quantity=4)],
            )
        )

    assert exc_info.value.status_code == 409
    assert sku.reserved_quantity == 3


def test_multi_sku_reserve_idempotency_key_allowed_by_real_schema() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    seller_id = uuid4()
    product_id = uuid4()
    sku_a_id = uuid4()
    sku_b_id = uuid4()
    order_id = uuid4()
    idempotency_key = str(uuid4())

    with Session(engine) as session:
        session.add(
            Seller(
                id=seller_id,
                email="seller@example.test",
                hashed_password="hash",
                company_name="Seller",
            )
        )
        session.add(
            Product(
                id=product_id,
                seller_id=seller_id,
                title="Phone",
                description="Last phone",
                category="electronics",
                status=ProductStatus.MODERATED,
            )
        )
        session.add_all(
            [
                SKU(
                    id=sku_a_id,
                    product_id=product_id,
                    name="Phone / Black",
                    price=100,
                    stock=10,
                    reserved_quantity=0,
                    images=[],
                ),
                SKU(
                    id=sku_b_id,
                    product_id=product_id,
                    name="Case / Black",
                    price=10,
                    stock=10,
                    reserved_quantity=0,
                    images=[],
                ),
            ]
        )
        session.flush()

        session.add(
            ReservationOperation(
                idempotency_key=idempotency_key,
                order_id=order_id,
            )
        )
        session.add_all(
            [
                Reservation(
                    sku_id=sku_a_id,
                    order_id=order_id,
                    quantity=1,
                    idempotency_key=idempotency_key,
                ),
                Reservation(
                    sku_id=sku_b_id,
                    order_id=order_id,
                    quantity=1,
                    idempotency_key=idempotency_key,
                ),
            ]
        )
        session.commit()

    Base.metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_reserve_all_skus_succeeds_on_real_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reservation_service_module, "SKURepository", SKURepository)
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationRepository",
        ReservationRepository,
    )
    monkeypatch.setattr(
        reservation_service_module,
        "ReservationOperationRepository",
        ReservationOperationRepository,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    seller_id = uuid4()
    product_id = uuid4()
    sku_a_id = uuid4()
    sku_b_id = uuid4()
    order_id = uuid4()
    idempotency_key = str(uuid4())

    with Session(engine) as session:
        session.add(
            Seller(
                id=seller_id,
                email="seller@example.test",
                hashed_password="hash",
                company_name="Seller",
            )
        )
        session.add(
            Product(
                id=product_id,
                seller_id=seller_id,
                title="Phone bundle",
                description="Last phone",
                category="electronics",
                status=ProductStatus.MODERATED,
            )
        )
        session.add_all(
            [
                SKU(
                    id=sku_a_id,
                    product_id=product_id,
                    name="Phone / Black",
                    price=100,
                    stock=5,
                    reserved_quantity=0,
                    images=[],
                ),
                SKU(
                    id=sku_b_id,
                    product_id=product_id,
                    name="Case / Black",
                    price=10,
                    stock=4,
                    reserved_quantity=1,
                    images=[],
                ),
            ]
        )
        session.commit()

        service = ReservationService(SyncSessionAdapter(session))
        request = _reserve_request(
            (sku_a_id, 2),
            (sku_b_id, 3),
            order_id=order_id,
            idempotency_key=idempotency_key,
        )
        FakeB2CClient.fail_delivery = True

        first = await service.reserve(request)
        second = await service.reserve(request)
        session.commit()

        sku_a = session.get(SKU, sku_a_id)
        sku_b = session.get(SKU, sku_b_id)
        reservations = (
            session.query(Reservation)
            .filter(Reservation.idempotency_key == idempotency_key)
            .all()
        )
        outbox_events = session.query(OutboxEvent).all()

        assert first == second
        assert sku_a is not None
        assert sku_a.stock == 5
        assert sku_a.reserved_quantity == 2
        assert sku_b is not None
        assert sku_b.stock == 4
        assert sku_b.reserved_quantity == 4
        assert len(reservations) == 2
        assert {reservation.sku_id for reservation in reservations} == {
            sku_a_id,
            sku_b_id,
        }
        assert len(outbox_events) == 1
        assert outbox_events[0].event_type == "SKU_OUT_OF_STOCK"
        assert outbox_events[0].status == "PENDING"
        assert outbox_events[0].payload["payload"]["sku_id"] == str(sku_b_id)
        assert session.get(ReservationOperation, idempotency_key) is not None

    Base.metadata.drop_all(engine)


def test_reserve_idempotency_key_unique_across_real_operations() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    idempotency_key = str(uuid4())

    with Session(engine) as session:
        session.add(
            ReservationOperation(
                idempotency_key=idempotency_key,
                order_id=uuid4(),
            )
        )
        session.commit()

        session.add(
            ReservationOperation(
                idempotency_key=idempotency_key,
                order_id=uuid4(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    Base.metadata.drop_all(engine)


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
    sku_id = uuid4()

    app.dependency_overrides[reservations_router.get_db] = _fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/inventory/unreserve",
            headers={"X-Service-Key": "dev-service-key-change-in-production"},
            json={
                "order_id": str(order_id),
                "items": [{"sku_id": str(sku_id), "quantity": 1}],
            },
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
    assert response.json()["code"] == "INSUFFICIENT_STOCK"
    assert response.json()["details"]["failed_items"][0]["available"] == 1
