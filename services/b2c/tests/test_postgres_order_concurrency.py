import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from src.models.order import Order, OrderStatus, PendingReservationCompensation
from src.models.user import User

def _database_url() -> str:
    url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")
    # These tests deliberately use synchronous SQLAlchemy sessions to create
    # genuinely concurrent PostgreSQL transactions, so they need a sync
    # driver even though the application itself uses asyncpg.
    return url.replace("+asyncpg", "+psycopg2", 1).replace("/b2b", "/b2c")


def _order(*, user_id: UUID, key: str, status: OrderStatus = OrderStatus.PAID) -> Order:
    return Order(
        id=uuid4(), user_id=user_id, status=status, total_amount=100,
        currency="RUB", idempotency_key=key, address_id=uuid4(),
        payment_method_id=uuid4(), address={"id": str(uuid4())},
        request_fingerprint="test",
    )


def _prepare(engine) -> UUID:
    user_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, hashed_password, is_active, created_at, updated_at) VALUES (:id, :email, 'h', true, now(), now())"),
            {"id": user_id, "email": f"{user_id}@test"},
        )
    return user_id


def _run_concurrently(operation):
    """Run two separate database transactions, with PostgreSQL lock timeouts."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operation) for _ in range(2)]
        # Docker Desktop can take longer than 15 seconds to establish two new
        # psycopg connections on Windows.  PostgreSQL still has its own 5s
        # lock timeout, while this watchdog only protects the test process.
        return [future.result(timeout=60) for future in futures]


def test_postgres_concurrent_checkout_key_returns_one_order() -> None:
    engine = create_engine(_database_url(), poolclass=NullPool)
    try:
        user_id, key = _prepare(engine), str(uuid4())

        def checkout() -> UUID:
            with Session(engine, expire_on_commit=False) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": key},
                )
                existing_id = session.scalar(
                    select(Order.id).where(Order.idempotency_key == key)
                )
                if existing_id is None:
                    created = _order(user_id=user_id, key=key)
                    session.add(created)
                    session.flush()
                    existing_id = created.id
                session.commit()
                return existing_id

        first, second = _run_concurrently(checkout)
        assert first == second
        with Session(engine) as session:
            assert session.query(Order).filter_by(idempotency_key=key).count() == 1
    finally:
        engine.dispose()


def test_postgres_concurrent_cancel_locks_single_order() -> None:
    engine = create_engine(_database_url(), poolclass=NullPool)
    try:
        user_id, key = _prepare(engine), str(uuid4())
        order = _order(user_id=user_id, key=key)
        order_id = order.id
        with Session(engine) as session:
            session.add(order)
            session.commit()

        def cancel() -> OrderStatus:
            with Session(engine, expire_on_commit=False) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                locked = session.scalar(
                    select(Order).where(Order.id == order_id).with_for_update()
                )
                assert locked is not None
                if locked.status is OrderStatus.PAID:
                    locked.status = OrderStatus.CANCELLED
                session.commit()
                return locked.status

        first, second = _run_concurrently(cancel)
        assert first is OrderStatus.CANCELLED and second is OrderStatus.CANCELLED
    finally:
        engine.dispose()


def test_postgres_checkout_retry_vs_compensation_serializes_operation() -> None:
    """A compensation winner tombstones before a retry can create an Order.

    Separate PostgreSQL connections intentionally model the recovery worker
    and a delayed checkout retry.  Both use the exact deterministic operation
    lock domain (the checkout order id), not unrelated idempotency-key locks.
    """
    engine = create_engine(_database_url(), poolclass=NullPool)
    try:
        user_id, key, operation_id = _prepare(engine), str(uuid4()), uuid4()
        with Session(engine) as session:
            session.add(
                PendingReservationCompensation(
                    order_id=operation_id,
                    items=[{"sku_id": str(uuid4()), "quantity": 1}],
                    attempts=1,
                    next_retry_at=datetime.now(timezone.utc),
                    last_error="ambiguous reserve",
                    request_fingerprint="test",
                )
            )
            session.commit()

        worker_checked, permit_compensation = Event(), Event()

        def compensate() -> str:
            with Session(engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:operation_id, 0))"),
                    {"operation_id": str(operation_id)},
                )
                assert session.get(Order, operation_id) is None
                worker_checked.set()
                assert permit_compensation.wait(timeout=10)
                pending = session.get(PendingReservationCompensation, operation_id)
                assert pending is not None
                pending.compensated_at = datetime.now(timezone.utc)
                pending.next_retry_at = None
                session.commit()
                return "COMPENSATED"

        def retry_checkout() -> str:
            assert worker_checked.wait(timeout=10)
            with Session(engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:operation_id, 0))"),
                    {"operation_id": str(operation_id)},
                )
                pending = session.get(PendingReservationCompensation, operation_id)
                assert pending is not None and pending.compensated_at is not None
                # This is the production checkout conflict branch: no Order is
                # inserted after compensation released the external reserve.
                return "CHECKOUT_OPERATION_COMPENSATED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            compensation = pool.submit(compensate)
            assert worker_checked.wait(timeout=10)
            checkout = pool.submit(retry_checkout)
            permit_compensation.set()
            assert compensation.result(timeout=30) == "COMPENSATED"
            assert checkout.result(timeout=30) == "CHECKOUT_OPERATION_COMPENSATED"

        with Session(engine) as session:
            assert session.get(Order, operation_id) is None
            pending = session.get(PendingReservationCompensation, operation_id)
            assert pending is not None and pending.compensated_at is not None
    finally:
        engine.dispose()
