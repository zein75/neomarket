from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.models.order import Order, OrderItem, OrderStatus
from src.schemas.order import OrderCreateRequest, OrderDetailResponse, OrderResponse
from src.services import order_service as order_service_module
from src.services.order_service import OrderService


pytestmark = pytest.mark.anyio


def _cart(*, user_id: UUID, items: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), user_id=user_id, currency="RUB", items=items)


def _cart_item(
    *,
    sku_id: UUID,
    product_id: UUID,
    quantity: int = 1,
    unit_price: int = 1000,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        cart_id=uuid4(),
        sku_id=sku_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
    )


def _order(*, user_id: UUID, status: OrderStatus) -> Order:
    sku_id = uuid4()
    item = OrderItem(
        sku_id=sku_id,
        product_id=uuid4(),
        product_title="Phone",
        sku_name="128 GB",
        quantity=2,
        unit_price=150,
        line_total=300,
    )
    item.id = uuid4()
    order = Order(
        user_id=user_id,
        status=status,
        total_amount=500,
        currency="RUB",
        idempotency_key=f"order-{uuid4()}",
        address_id=uuid4(),
        address={
            "id": str(uuid4()),
            "country": "RU",
            "city": "Yekaterinburg",
            "street": "Mira",
            "building": "19",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    order.id = uuid4()
    order.items = [item]
    return order


def _order_with_total(
    *,
    user_id: UUID,
    status: OrderStatus,
    total_amount: int,
) -> Order:
    order = _order(user_id=user_id, status=status)
    order.total_amount = total_amount
    return order


def _unreserve_payload(order: Order) -> dict[str, object]:
    return {
        "order_id": str(order.id),
        "items": [
            {"sku_id": str(item.sku_id), "quantity": item.quantity}
            for item in order.items
        ],
    }


def _order_request() -> OrderCreateRequest:
    return OrderCreateRequest(address_id=uuid4(), payment_method_id=uuid4())


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flushed = False
        self.rolled_back = False
        self.committed = False
        self.fail_flush = False
        self.fail_commit_at: int | None = None
        self.commit_calls = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True
        if self.fail_flush:
            raise RuntimeError("database write failed")

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.fail_commit_at == self.commit_calls:
            raise RuntimeError("database commit failed")
        self.committed = True

    async def delete(self, obj) -> None:
        return None


class FakeCartRepository:
    cart: SimpleNamespace | None = None
    removed_items: list[UUID] = []

    def __init__(self, session) -> None:
        self.session = session

    async def get_with_items(self, cart_id: UUID):
        if self.cart and self.cart.id == cart_id:
            return self.cart
        return None

    async def remove_item(self, item) -> None:
        self.removed_items.append(item.id)


class FakeOrderRepository:
    orders_by_key: dict[str, Order] = {}
    orders_by_id: dict[UUID, Order] = {}
    pending_fulfillments: dict[UUID, SimpleNamespace] = {}
    pending_reservation_compensations: dict[UUID, SimpleNamespace] = {}
    created_orders: list[Order] = []
    locked_gets: list[UUID] = []
    race_order: Order | None = None
    raise_integrity_error = False

    def __init__(self, session) -> None:
        self.session = session

    async def get_by_idempotency_key(self, idempotency_key: str):
        return self.orders_by_key.get(idempotency_key)

    async def get_with_items(self, order_id: UUID):
        if order_id in self.orders_by_id:
            return self.orders_by_id[order_id]
        for order in self.created_orders:
            if order.id == order_id:
                return order
        return None

    async def get_with_items_for_update(self, order_id: UUID):
        self.locked_gets.append(order_id)
        return await self.get_with_items(order_id)

    async def get_user_order_with_items(self, order_id: UUID, user_id: UUID):
        order = await self.get_with_items(order_id)
        if order and order.user_id == user_id:
            return order
        return None

    async def list_by_status(self, status: OrderStatus, limit: int = 100):
        return [
            order
            for order in self.orders_by_id.values()
            if order.status == status
        ][:limit]

    async def list_due_cancellation_retries(self, now, limit: int = 100):
        return [
            order
            for order in self.orders_by_id.values()
            if order.status == OrderStatus.CANCEL_PENDING
            and (
                getattr(order, "cancel_retry_at", None) is None
                or order.cancel_retry_at <= now
            )
        ][:limit]

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        status_filter: OrderStatus | None = None,
    ):
        orders = [
            order
            for order in self.orders_by_id.values()
            if order.user_id == user_id
            and (status_filter is None or order.status == status_filter)
        ]
        orders.sort(key=lambda order: str(order.id), reverse=True)
        return orders[offset : offset + limit], len(orders)

    async def create(self, **data):
        if self.raise_integrity_error:
            self.raise_integrity_error = False
            if self.race_order is not None:
                self.orders_by_key[self.race_order.idempotency_key] = self.race_order
            raise IntegrityError("insert", {}, Exception("duplicate idempotency key"))
        order = Order(**data)
        order.id = data.get("id") or uuid4()
        order.items = []
        self.created_orders.append(order)
        self.orders_by_key[order.idempotency_key] = order
        self.orders_by_id[order.id] = order
        return order

    async def get_pending_fulfillment(self, order_id: UUID):
        return self.pending_fulfillments.get(order_id)

    async def queue_fulfillment_retry(self, order: Order, error: str):
        pending = self.pending_fulfillments.get(order.id)
        if pending is None:
            pending = SimpleNamespace(
                order_id=order.id,
                order=order,
                attempts=1,
                last_error=error,
            )
            self.pending_fulfillments[order.id] = pending
        else:
            pending.attempts += 1
            pending.last_error = error
        return pending

    async def list_pending_fulfillments(self, *, limit: int = 100):
        return list(self.pending_fulfillments.values())[:limit]

    async def delete_pending_fulfillment(self, pending) -> None:
        self.pending_fulfillments.pop(pending.order_id, None)

    async def queue_reservation_compensation(
        self, *, order_id, items, error, next_retry_at, request_fingerprint=None
    ):
        pending = self.pending_reservation_compensations.get(order_id)
        if pending is None:
            pending = SimpleNamespace(
                order_id=order_id,
                items=items,
                attempts=1,
                next_retry_at=next_retry_at,
                last_error=error,
                request_fingerprint=request_fingerprint,
            )
            self.pending_reservation_compensations[order_id] = pending
        else:
            pending.attempts += 1
            pending.next_retry_at = next_retry_at
            pending.last_error = error
            if request_fingerprint is not None:
                pending.request_fingerprint = request_fingerprint
        return pending

    async def get_reservation_compensation(self, order_id):
        return self.pending_reservation_compensations.get(order_id)

    async def list_due_reservation_compensations(self, now, limit: int = 100):
        return [
            pending
            for pending in self.pending_reservation_compensations.values()
            if pending.next_retry_at is None or pending.next_retry_at <= now
        ][:limit]

    async def delete_reservation_compensation(self, pending) -> None:
        self.pending_reservation_compensations.pop(pending.order_id, None)


class FakeAddressRepository:
    return_none = False
    def __init__(self, session) -> None:
        self.session = session

    async def get_for_user(self, address_id: UUID, user_id: UUID):
        if self.return_none:
            return None
        return SimpleNamespace(
            id=address_id,
            user_id=user_id,
            country="RU",
            region=None,
            city="Yekaterinburg",
            street="Mira",
            building="19",
            apartment=None,
            postal_code=None,
            recipient_name=None,
            recipient_phone=None,
            is_default=False,
            comment=None,
            created_at=datetime.now(timezone.utc),
        )


class FakeB2BClient:
    products: list[dict[str, object]] = []
    reserve_calls: list[dict[str, object]] = []
    unreserve_calls: list[dict[str, object]] = []
    fulfill_calls: list[dict[str, object]] = []
    reserve_error: HTTPException | None = None
    unreserve_error: HTTPException | None = None
    fulfill_error: HTTPException | None = None

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get_products_batch(self, product_ids: list[str]):
        return [
            product
            for product in self.products
            if str(product.get("id")) in set(product_ids)
        ]

    async def reserve(self, payload: dict[str, object]):
        self.reserve_calls.append(payload)
        if self.reserve_error:
            raise self.reserve_error
        return {"status": "RESERVED", "order_id": payload["order_id"]}

    async def unreserve(self, payload: dict[str, object]):
        self.unreserve_calls.append(payload)
        if self.unreserve_error:
            raise self.unreserve_error
        return {"status": "UNRESERVED", "order_id": payload["order_id"]}

    async def fulfill(self, payload: dict[str, object]):
        self.fulfill_calls.append(payload)
        if self.fulfill_error:
            raise self.fulfill_error
        return {"status": "FULFILLED", "order_id": payload["order_id"]}


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeCartRepository.cart = None
    FakeCartRepository.removed_items = []
    FakeOrderRepository.orders_by_key = {}
    FakeOrderRepository.orders_by_id = {}
    FakeOrderRepository.pending_fulfillments = {}
    FakeOrderRepository.pending_reservation_compensations = {}
    FakeOrderRepository.created_orders = []
    FakeOrderRepository.locked_gets = []
    FakeOrderRepository.race_order = None
    FakeOrderRepository.raise_integrity_error = False
    FakeAddressRepository.return_none = False
    FakeB2BClient.products = []
    FakeB2BClient.reserve_calls = []
    FakeB2BClient.unreserve_calls = []
    FakeB2BClient.fulfill_calls = []
    FakeB2BClient.reserve_error = None
    FakeB2BClient.unreserve_error = None
    FakeB2BClient.fulfill_error = None
    monkeypatch.setattr(order_service_module, "CartRepository", FakeCartRepository)
    monkeypatch.setattr(order_service_module, "OrderRepository", FakeOrderRepository)
    monkeypatch.setattr(order_service_module, "AddressRepository", FakeAddressRepository)
    monkeypatch.setattr(order_service_module, "B2BClient", FakeB2BClient, raising=False)


async def test_checkout_creates_paid_order_with_fixed_prices() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    order_request = _order_request()
    cart_item = _cart_item(
        product_id=product_id,
        sku_id=sku_id,
        quantity=2,
        unit_price=100,
    )
    cart = _cart(user_id=user_id, items=[cart_item])
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "128 GB",
                    "price": 150,
                    "active_quantity": 5,
                }
            ],
        }
    ]

    order = await OrderService(FakeSession()).checkout(
        user_id=user_id,
        cart_id=cart.id,
        idempotency_key="checkout-1",
        order_request=order_request,
    )

    assert order.status == OrderStatus.PAID
    assert order.total_amount == 300
    assert order.idempotency_key == "checkout-1"
    assert order.address_id == order_request.address_id
    assert order.payment_method_id == order_request.payment_method_id
    assert order.address["id"] == str(order_request.address_id)
    assert order.address["country"] == "RU"
    assert order.address["city"] == "Yekaterinburg"
    assert order.address["street"] == "Mira"
    assert order.address["building"] == "19"
    assert order.address["created_at"]
    assert order.items[0].unit_price == 150
    assert order.items[0].product_title == "Phone"
    assert order.items[0].sku_name == "128 GB"
    response = OrderResponse.model_validate(order).model_dump(mode="json")
    assert response["buyer_id"] == str(user_id)
    assert response["subtotal"] == 300
    assert response["total"] == 300
    assert response["address"]["id"] == str(order_request.address_id)
    assert response["address"]["country"] == "RU"
    assert response["address"]["city"] == "Yekaterinburg"
    assert response["address"]["street"] == "Mira"
    assert response["address"]["building"] == "19"
    assert response["address"]["created_at"]
    assert response["created_at"]
    assert response["items"][0]["name"] == "Phone 128 GB"
    assert FakeB2BClient.reserve_calls == [
        {
            "order_id": str(order.id),
            "idempotency_key": "checkout-1",
            "items": [{"sku_id": str(sku_id), "quantity": 2}],
        }
    ]
    assert FakeCartRepository.removed_items == []


async def test_partial_reserve_failure_returns_409() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id, quantity=2)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "128 GB",
                    "price": 150,
                    "active_quantity": 5,
                }
            ],
        }
    ]
    FakeB2BClient.reserve_error = HTTPException(
        status_code=409,
        detail={
            "code": "INSUFFICIENT_STOCK",
            "message": "Insufficient stock",
            "details": {"failed_items": [{"sku_id": str(sku_id)}]},
        },
    )

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-2",
            order_request=_order_request(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "RESERVE_FAILED",
        "message": "Unable to reserve one or more items",
        "failed_items": [{"sku_id": str(sku_id)}],
    }
    assert FakeOrderRepository.created_orders == []
    assert FakeCartRepository.removed_items == []


async def test_idempotency_returns_existing_order() -> None:
    user_id = uuid4()
    existing = Order(
        user_id=user_id,
        status=OrderStatus.PAID,
        total_amount=500,
        currency="RUB",
        idempotency_key="checkout-3",
    )
    existing.id = uuid4()
    existing.items = []
    FakeOrderRepository.orders_by_key["checkout-3"] = existing

    order = await OrderService(FakeSession()).checkout(
        user_id=user_id,
        cart_id=uuid4(),
        idempotency_key="checkout-3",
    )

    assert order is existing
    assert FakeB2BClient.reserve_calls == []
    assert FakeOrderRepository.created_orders == []


async def test_concurrent_idempotency_race_returns_existing_order() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    order_request = _order_request()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "128 GB",
                    "price": 150,
                    "active_quantity": 5,
                }
            ],
        }
    ]
    existing = Order(
        user_id=user_id,
        status=OrderStatus.PAID,
        total_amount=150,
        currency="RUB",
        idempotency_key="checkout-race",
        address_id=order_request.address_id,
        payment_method_id=order_request.payment_method_id,
    )
    existing.id = uuid4()
    existing.items = []
    FakeOrderRepository.race_order = existing
    FakeOrderRepository.raise_integrity_error = True
    session = FakeSession()
    service = OrderService(session)
    existing.request_fingerprint = service._request_fingerprint(order_request)

    order = await service.checkout(
        user_id=user_id,
        cart_id=cart.id,
        idempotency_key="checkout-race",
        order_request=order_request,
    )

    assert order is existing
    assert session.rolled_back is True
    assert service.last_checkout_replayed is True
    # Both concurrent deliveries use the same deterministic B2B operation.
    # Compensating it here would unreserve the winning order.
    assert FakeB2BClient.unreserve_calls == []


async def test_duplicate_checkout_reuses_winning_reservation_without_compensation() -> None:
    user_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
    request = _order_request()
    FakeCartRepository.cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id)],
    )
    FakeB2BClient.products = [{
        "id": str(product_id),
        "title": "Phone",
        "skus": [{"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}],
    }]
    existing = _order(user_id=user_id, status=OrderStatus.PAID)
    existing.idempotency_key = "checkout-race-compensation"
    existing.request_fingerprint = OrderService(FakeSession())._request_fingerprint(request)
    FakeOrderRepository.race_order = existing
    FakeOrderRepository.raise_integrity_error = True
    session = FakeSession()

    order = await OrderService(session).checkout(
        user_id=user_id,
        cart_id=FakeCartRepository.cart.id,
        idempotency_key="checkout-race-compensation",
        order_request=request,
    )

    assert order is existing
    assert FakeOrderRepository.pending_reservation_compensations == {}
    assert FakeB2BClient.unreserve_calls == []


async def test_idempotency_with_different_body_returns_409() -> None:
    user_id = uuid4()
    service = OrderService(FakeSession())
    original_request = _order_request()
    existing = Order(
        user_id=user_id,
        status=OrderStatus.PAID,
        total_amount=500,
        currency="RUB",
        address_id=original_request.address_id,
        payment_method_id=original_request.payment_method_id,
        address={},
        idempotency_key="checkout-3",
        request_fingerprint=service._request_fingerprint(original_request),
    )
    existing.id = uuid4()
    existing.items = []
    FakeOrderRepository.orders_by_key["checkout-3"] = existing

    with pytest.raises(HTTPException) as exc:
        await service.checkout(
            user_id=user_id,
            cart_id=uuid4(),
            idempotency_key="checkout-3",
            order_request=_order_request(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "IDEMPOTENCY_KEY_REUSED",
        "message": "Idempotency key was already used with a different request body",
    }
    assert FakeB2BClient.reserve_calls == []
    assert FakeOrderRepository.created_orders == []


async def test_idempotency_key_does_not_return_another_users_order() -> None:
    owner_id = uuid4()
    existing = Order(
        user_id=owner_id,
        status=OrderStatus.PAID,
        total_amount=500,
        currency="RUB",
        idempotency_key="checkout-owned",
    )
    existing.id = uuid4()
    existing.items = []
    FakeOrderRepository.orders_by_key["checkout-owned"] = existing

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=uuid4(),
            cart_id=uuid4(),
            idempotency_key="checkout-owned",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ORDER_NOT_FOUND"
    assert FakeB2BClient.reserve_calls == []


async def test_idempotency_with_different_body_returns_409_for_legacy_order() -> None:
    user_id = uuid4()
    original_request = _order_request()
    existing = Order(
        user_id=user_id,
        status=OrderStatus.PAID,
        total_amount=500,
        currency="RUB",
        address_id=original_request.address_id,
        payment_method_id=original_request.payment_method_id,
        address={},
        idempotency_key="checkout-legacy",
    )
    existing.id = uuid4()
    existing.items = []
    FakeOrderRepository.orders_by_key["checkout-legacy"] = existing

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=uuid4(),
            idempotency_key="checkout-legacy",
            order_request=_order_request(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert FakeB2BClient.reserve_calls == []
    assert FakeOrderRepository.created_orders == []


async def test_b2b_unavailable_returns_503() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id, quantity=1)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "128 GB",
                    "price": 150,
                    "active_quantity": 5,
                }
            ],
        }
    ]
    FakeB2BClient.reserve_error = HTTPException(
        status_code=503,
        detail="B2B service unavailable",
    )

    request = _order_request()
    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-4",
            order_request=request,
        )

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "B2B_UNAVAILABLE"
    assert FakeOrderRepository.created_orders == []
    # A timeout can happen after B2B accepted reserve. Keep the intent so a
    # same-key retry is idempotent and a crash can be compensated by the worker.
    order_id = UUID(FakeB2BClient.reserve_calls[0]["order_id"])
    assert order_id in FakeOrderRepository.pending_reservation_compensations
    assert (
        FakeOrderRepository.pending_reservation_compensations[order_id]
        .request_fingerprint
        == OrderService(FakeSession())._request_fingerprint(request)
    )

    # If B2B had actually reserved before its response was lost, the stable
    # operation identity makes the retry a replay rather than a double reserve.
    FakeB2BClient.reserve_error = None
    retried = await OrderService(FakeSession()).checkout(
        user_id=user_id,
        cart_id=cart.id,
        idempotency_key="checkout-4",
        order_request=request,
    )
    assert retried.id == order_id
    assert len(FakeB2BClient.reserve_calls) == 2
    assert FakeB2BClient.unreserve_calls == []


async def test_checkout_rejects_address_not_owned_by_buyer() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id)],
    )
    FakeCartRepository.cart = cart
    FakeAddressRepository.return_none = True

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-address-missing",
            order_request=_order_request(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ADDRESS_NOT_FOUND"
    assert FakeB2BClient.reserve_calls == []


async def test_checkout_compensates_reserve_when_persistence_fails() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id, quantity=2)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}
            ],
        }
    ]
    session = FakeSession()
    session.fail_flush = True

    with pytest.raises(RuntimeError, match="database write failed"):
        await OrderService(session).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-compensate",
            order_request=_order_request(),
        )

    assert session.rolled_back is True
    assert FakeB2BClient.unreserve_calls == [
        {
            "order_id": FakeB2BClient.reserve_calls[0]["order_id"],
            "items": [{"sku_id": str(sku_id), "quantity": 2}],
        }
    ]


async def test_checkout_compensates_reserve_when_created_order_cannot_reload() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id, quantity=2)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Phone",
            "skus": [
                {"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}
            ],
        }
    ]
    service = OrderService(FakeSession())

    async def missing_reloaded_order(order_id: UUID):
        return None

    service.order_repo.get_with_items = missing_reloaded_order

    with pytest.raises(RuntimeError, match="could not be reloaded"):
        await service.checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-reload-failure",
            order_request=_order_request(),
        )

    assert FakeB2BClient.unreserve_calls == [
        {
            "order_id": FakeB2BClient.reserve_calls[0]["order_id"],
            "items": [{"sku_id": str(sku_id), "quantity": 2}],
        }
    ]


async def test_checkout_persists_compensation_when_unreserve_also_fails() -> None:
    user_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
    cart = _cart(
        user_id=user_id,
        items=[_cart_item(product_id=product_id, sku_id=sku_id, quantity=2)],
    )
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [{
        "id": str(product_id), "title": "Phone",
        "skus": [{"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}],
    }]
    FakeB2BClient.unreserve_error = HTTPException(status_code=503, detail="down")
    session = FakeSession()
    session.fail_flush = True

    with pytest.raises(RuntimeError, match="database write failed"):
        await OrderService(session).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-durable-compensation",
            order_request=_order_request(),
        )

    order_id = UUID(FakeB2BClient.reserve_calls[0]["order_id"])
    pending = FakeOrderRepository.pending_reservation_compensations[order_id]
    assert pending.items == [{"sku_id": str(sku_id), "quantity": 2}]
    assert session.committed is True


async def test_pending_checkout_compensation_retries_after_b2b_recovers() -> None:
    order_id, sku_id = uuid4(), uuid4()
    FakeOrderRepository.pending_reservation_compensations[order_id] = SimpleNamespace(
        order_id=order_id,
        items=[{"sku_id": str(sku_id), "quantity": 2}],
        attempts=1,
        next_retry_at=datetime.now(timezone.utc),
        last_error="B2B unavailable",
    )

    retried = await OrderService(FakeSession()).retry_pending_reservation_compensations()

    assert retried == 1
    assert FakeOrderRepository.pending_reservation_compensations == {}
    assert FakeB2BClient.unreserve_calls == [{
        "order_id": str(order_id),
        "items": [{"sku_id": str(sku_id), "quantity": 2}],
    }]


async def test_orders_list_returns_own_orders_paginated() -> None:
    user_id = uuid4()
    own_paid = _order_with_total(
        user_id=user_id,
        status=OrderStatus.PAID,
        total_amount=300,
    )
    own_delivered = _order_with_total(
        user_id=user_id,
        status=OrderStatus.DELIVERED,
        total_amount=900,
    )
    other_user_order = _order_with_total(
        user_id=uuid4(),
        status=OrderStatus.PAID,
        total_amount=100,
    )
    FakeOrderRepository.orders_by_id = {
        own_paid.id: own_paid,
        own_delivered.id: own_delivered,
        other_user_order.id: other_user_order,
    }

    response = await OrderService(FakeSession()).list_orders(
        user_id,
        limit=1,
        offset=0,
        status_filter=OrderStatus.PAID,
    )
    payload = response.model_dump(mode="json")

    assert payload["total_count"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == str(own_paid.id)
    assert payload["items"][0]["status"] == "PAID"
    assert payload["items"][0]["buyer_id"] == str(user_id)
    assert payload["items"][0]["subtotal"] == 300
    assert payload["items"][0]["total"] == 300
    assert payload["items"][0]["address"]["country"] == "RU"


async def test_order_detail_shows_fixed_prices() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.PAID)
    order.total_amount = 300
    order.items[0].unit_price = 150
    order.items[0].line_total = 300
    FakeOrderRepository.orders_by_id[order.id] = order

    loaded = await OrderService(FakeSession()).get_order(order.id, user_id)
    payload = OrderDetailResponse.model_validate(loaded).model_dump(mode="json")

    assert payload["id"] == str(order.id)
    assert payload["total_amount"] == 300
    assert payload["items"][0]["unit_price"] == 150
    assert payload["items"][0]["line_total"] == 300
    assert payload["items"][0]["product_title"] == "Phone"
    assert payload["items"][0]["sku_name"] == "128 GB"


async def test_other_user_order_returns_404_not_403() -> None:
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).get_order(
            order_id=order.id,
            user_id=uuid4(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ORDER_NOT_FOUND"


async def test_delivered_status_triggers_fulfill_to_b2b() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERING)
    FakeOrderRepository.orders_by_id[order.id] = order

    delivered = await OrderService(FakeSession()).mark_delivered(order.id)

    assert delivered.status == OrderStatus.DELIVERED
    assert FakeOrderRepository.locked_gets == [order.id]
    assert FakeB2BClient.fulfill_calls == [
        {
            "order_id": str(order.id),
            "items": [
                {
                    "sku_id": str(order.items[0].sku_id),
                    "quantity": order.items[0].quantity,
                }
            ],
        }
    ]
    assert FakeOrderRepository.pending_fulfillments == {}


async def test_fulfill_failure_retried_asynchronously() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERING)
    FakeOrderRepository.orders_by_id[order.id] = order
    FakeB2BClient.fulfill_error = HTTPException(
        status_code=503,
        detail="B2B service unavailable",
    )

    delivered = await OrderService(FakeSession()).mark_delivered(order.id)

    assert delivered.status == OrderStatus.DELIVERED
    assert order.id in FakeOrderRepository.pending_fulfillments
    assert FakeOrderRepository.pending_fulfillments[order.id].attempts == 1

    FakeB2BClient.fulfill_error = None
    retried = await OrderService(FakeSession()).retry_pending_fulfillments()

    assert retried == 1
    assert FakeOrderRepository.pending_fulfillments == {}
    assert len(FakeB2BClient.fulfill_calls) == 2


async def test_repeated_fulfill_idempotent() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERED)
    FakeOrderRepository.orders_by_id[order.id] = order

    first = await OrderService(FakeSession()).mark_delivered(order.id)
    second = await OrderService(FakeSession()).mark_delivered(order.id)

    assert first.status == OrderStatus.DELIVERED
    assert second.status == OrderStatus.DELIVERED
    assert FakeB2BClient.fulfill_calls == [
        {
            "order_id": str(order.id),
            "items": [
                {
                    "sku_id": str(order.items[0].sku_id),
                    "quantity": order.items[0].quantity,
                }
            ],
        },
        {
            "order_id": str(order.id),
            "items": [
                {
                    "sku_id": str(order.items[0].sku_id),
                    "quantity": order.items[0].quantity,
                }
            ],
        },
    ]


async def test_cancelled_order_delivery_does_not_fulfill() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.CANCELLED)
    FakeOrderRepository.orders_by_id[order.id] = order

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).mark_delivered(order.id)

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "DELIVERY_NOT_ALLOWED",
        "message": "Order cannot be delivered in current status",
        "current_status": "CANCELLED",
    }
    assert order.status == OrderStatus.CANCELLED
    assert FakeB2BClient.fulfill_calls == []


async def test_cancel_paid_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.PAID)
    order.address_id = UUID(order.address["id"])
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(
        order_id=order.id,
        user_id=user_id,
    )

    assert cancelled.status == OrderStatus.CANCELLED
    assert FakeOrderRepository.locked_gets == [order.id]
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]
    response = OrderResponse.model_validate(cancelled).model_dump(mode="json")
    assert response["address"]["id"] == str(order.address_id)
    assert response["address"]["country"] == "RU"
    assert response["address"]["city"] == "Yekaterinburg"
    assert response["address"]["street"] == "Mira"
    assert response["address"]["building"] == "19"
    assert response["address"]["created_at"]
    assert response["status_history"][-1]["status"] == "CANCELLED"


async def test_unreserve_failure_transitions_to_cancel_pending() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.PAID)
    order.address_id = UUID(order.address["id"])
    FakeOrderRepository.orders_by_id[order.id] = order
    FakeB2BClient.unreserve_error = HTTPException(
        status_code=503,
        detail="B2B service unavailable",
    )

    pending = await OrderService(FakeSession()).cancel_order(
        order_id=order.id,
        user_id=user_id,
    )

    assert pending.status == OrderStatus.CANCEL_PENDING
    assert pending.cancel_retry_attempts == 1
    assert pending.cancel_retry_at is not None
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]
    response = OrderResponse.model_validate(pending).model_dump(mode="json")
    assert response["address"]["id"] == str(order.address_id)
    assert response["address"]["country"] == "RU"
    assert response["address"]["city"] == "Yekaterinburg"
    assert response["address"]["street"] == "Mira"
    assert response["address"]["building"] == "19"
    assert response["address"]["created_at"]
    assert response["status_history"][-1]["status"] == "CANCEL_PENDING"


async def test_pending_cancellation_is_retried_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.CANCEL_PENDING)
    order.cancel_reason = "Changed my mind"
    FakeOrderRepository.orders_by_id[order.id] = order

    retried = await OrderService(FakeSession()).retry_pending_cancellations()

    assert retried == 1
    assert order.status == OrderStatus.CANCELLED
    assert order.cancel_retry_at is None
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]
    assert order.status_history[-1].status == OrderStatus.CANCELLED


async def test_cancel_assembling_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.ASSEMBLING)
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(order.id, user_id)

    assert cancelled.status == OrderStatus.CANCELLED
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_delivering_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERING)
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(order.id, user_id)

    assert cancelled.status == OrderStatus.CANCELLED
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_delivered_order_returns_409() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERED)
    FakeOrderRepository.orders_by_id[order.id] = order

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).cancel_order(
            order_id=order.id,
            user_id=user_id,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "CANCEL_NOT_ALLOWED",
        "message": "Order cannot be cancelled in current status",
        "current_status": "DELIVERED",
    }
    assert FakeB2BClient.unreserve_calls == []


async def test_other_user_order_returns_404() -> None:
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).cancel_order(
            order_id=order.id,
            user_id=uuid4(),
        )

    assert exc.value.status_code == 404
    assert FakeB2BClient.unreserve_calls == []


async def test_checkout_final_commit_failure_compensates_durable_reserve() -> None:
    """A router commit can no longer leak a successful B2B reservation."""
    user_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
    request = _order_request()
    cart = _cart(user_id=user_id, items=[_cart_item(product_id=product_id, sku_id=sku_id)])
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [{
        "id": str(product_id), "title": "Phone",
        "skus": [{"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}],
    }]
    session = FakeSession()
    # Commit 1 persists intent; commit 2 is the order confirmation and fails.
    session.fail_commit_at = 2

    with pytest.raises(RuntimeError, match="database commit failed"):
        await OrderService(session).checkout(user_id, cart.id, "commit-failure", request)

    assert len(FakeB2BClient.reserve_calls) == 1
    assert len(FakeB2BClient.unreserve_calls) == 1
    assert session.rolled_back is True


async def test_checkout_commit_failure_with_unreserve_failure_keeps_durable_intent() -> None:
    user_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
    request = _order_request()
    cart = _cart(user_id=user_id, items=[_cart_item(product_id=product_id, sku_id=sku_id)])
    FakeCartRepository.cart = cart
    FakeB2BClient.products = [{
        "id": str(product_id), "title": "Phone",
        "skus": [{"id": str(sku_id), "name": "128 GB", "price": 150, "active_quantity": 5}],
    }]
    session = FakeSession()
    session.fail_commit_at = 2
    FakeB2BClient.unreserve_error = HTTPException(status_code=503, detail="down")

    with pytest.raises(RuntimeError, match="database commit failed"):
        await OrderService(session).checkout(user_id, cart.id, "commit-compensation", request)

    reserve_id = UUID(FakeB2BClient.reserve_calls[0]["order_id"])
    pending = FakeOrderRepository.pending_reservation_compensations[reserve_id]
    assert pending.items == [{"sku_id": str(sku_id), "quantity": 1}]
    assert "unreserve" in pending.last_error


async def test_compensation_worker_never_unreserves_committed_order() -> None:
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order
    await FakeOrderRepository(FakeSession()).queue_reservation_compensation(
        order_id=order.id,
        items=[{"sku_id": str(order.items[0].sku_id), "quantity": 2}],
        error="stale intent",
        next_retry_at=None,
    )

    retried = await OrderService(FakeSession()).retry_pending_reservation_compensations()

    assert retried == 1
    assert FakeB2BClient.unreserve_calls == []
    assert FakeOrderRepository.pending_reservation_compensations == {}


async def test_cancel_pending_is_committed_before_unreserve() -> None:
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order
    session = FakeSession()

    await OrderService(session).cancel_order(order.id, order.user_id)

    # First commit happens with CANCEL_PENDING, before the external call.
    assert session.commit_calls >= 2
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_final_commit_failure_leaves_durable_pending_for_retry() -> None:
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order
    session = FakeSession()
    session.fail_commit_at = 2

    await OrderService(session).cancel_order(order.id, order.user_id)

    assert session.rolled_back is True
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_pending_commit_failure_does_not_call_unreserve() -> None:
    """No external side effect is allowed before CANCEL_PENDING is durable."""
    order = _order(user_id=uuid4(), status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order
    session = FakeSession()
    session.fail_commit_at = 1

    with pytest.raises(RuntimeError, match="database commit failed"):
        await OrderService(session).cancel_order(order.id, order.user_id)

    assert FakeB2BClient.unreserve_calls == []
