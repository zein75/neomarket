import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.models.order import Order, OrderStatus
from src.models.user import User
from src.repositories.order_repo import OrderRepository


class SyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params)


def _database_url() -> str:
    url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")
    return url.replace("/b2b", "/b2c")


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
        connection.execute(text("TRUNCATE orders, users CASCADE"))
        connection.execute(
            text("INSERT INTO users (id, email, hashed_password, is_active, created_at, updated_at) VALUES (:id, :email, 'h', true, now(), now())"),
            {"id": user_id, "email": f"{user_id}@test"},
        )
    return user_id


def test_postgres_concurrent_checkout_key_returns_one_order() -> None:
    engine = create_engine(_database_url())
    user_id, key = _prepare(engine), str(uuid4())

    def checkout() -> UUID:
        with Session(engine) as session:
            repo = OrderRepository(SyncSessionAdapter(session))
            asyncio.run(repo.lock_idempotency_key(key))
            existing = asyncio.run(repo.get_by_idempotency_key(key))
            if existing is None:
                existing = _order(user_id=user_id, key=key)
                session.add(existing)
            session.commit()
            return existing.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: checkout(), range(2)))
    assert first == second
    with Session(engine) as session:
        assert session.query(Order).filter_by(idempotency_key=key).count() == 1


def test_postgres_concurrent_cancel_locks_single_order() -> None:
    engine = create_engine(_database_url())
    user_id, key = _prepare(engine), str(uuid4())
    order = _order(user_id=user_id, key=key)
    with Session(engine) as session:
        session.add(order)
        session.commit()

    def cancel() -> OrderStatus:
        with Session(engine) as session:
            repo = OrderRepository(SyncSessionAdapter(session))
            locked = asyncio.run(repo.get_with_items_for_update(order.id))
            if locked.status is OrderStatus.PAID:
                locked.status = OrderStatus.CANCELLED
            session.commit()
            return locked.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: cancel(), range(2)))
    assert first is OrderStatus.CANCELLED and second is OrderStatus.CANCELLED
