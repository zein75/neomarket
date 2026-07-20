from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.models.order import Order, OrderItem, OrderStatus
from src.schemas.order import OrderCreateRequest, OrderResponse
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
    )
    order.id = uuid4()
    order.items = [item]
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

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


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
    created_orders: list[Order] = []

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

    async def create(self, **data):
        order = Order(**data)
        order.id = data.get("id") or uuid4()
        order.items = []
        self.created_orders.append(order)
        self.orders_by_key[order.idempotency_key] = order
        self.orders_by_id[order.id] = order
        return order


class FakeB2BClient:
    products: list[dict[str, object]] = []
    reserve_calls: list[dict[str, object]] = []
    unreserve_calls: list[dict[str, object]] = []
    reserve_error: HTTPException | None = None
    unreserve_error: HTTPException | None = None

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


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeCartRepository.cart = None
    FakeCartRepository.removed_items = []
    FakeOrderRepository.orders_by_key = {}
    FakeOrderRepository.orders_by_id = {}
    FakeOrderRepository.created_orders = []
    FakeB2BClient.products = []
    FakeB2BClient.reserve_calls = []
    FakeB2BClient.unreserve_calls = []
    FakeB2BClient.reserve_error = None
    FakeB2BClient.unreserve_error = None
    monkeypatch.setattr(order_service_module, "CartRepository", FakeCartRepository)
    monkeypatch.setattr(order_service_module, "OrderRepository", FakeOrderRepository)
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
    assert order.address == {"id": str(order_request.address_id)}
    assert order.items[0].unit_price == 150
    assert order.items[0].product_title == "Phone"
    assert order.items[0].sku_name == "128 GB"
    response = OrderResponse.model_validate(order).model_dump(mode="json")
    assert response["buyer_id"] == str(user_id)
    assert response["subtotal"] == 300
    assert response["total"] == 300
    assert response["address"] == {"id": str(order_request.address_id)}
    assert response["created_at"]
    assert response["items"][0]["name"] == "Phone 128 GB"
    assert "total_amount" not in response
    assert "product_title" not in response["items"][0]
    assert "sku_name" not in response["items"][0]
    assert FakeB2BClient.reserve_calls == [
        {
            "order_id": str(order.id),
            "idempotency_key": "checkout-1",
            "items": [{"sku_id": str(sku_id), "quantity": 2}],
        }
    ]
    assert FakeCartRepository.removed_items == [cart_item.id]


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
        detail={"code": "RESERVE_FAILED", "failed_items": [{"sku_id": str(sku_id)}]},
    )

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-2",
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
        status=OrderStatus.CONFIRMED,
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

    with pytest.raises(HTTPException) as exc:
        await OrderService(FakeSession()).checkout(
            user_id=user_id,
            cart_id=cart.id,
            idempotency_key="checkout-4",
        )

    assert exc.value.status_code == 503
    assert FakeOrderRepository.created_orders == []


async def test_cancel_paid_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.PAID)
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(
        order_id=order.id,
        user_id=user_id,
    )

    assert cancelled.status == OrderStatus.CANCELLED
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_unreserve_failure_transitions_to_cancel_pending() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.PAID)
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
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_assembling_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.ASSEMBLING)
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(
        order_id=order.id,
        user_id=user_id,
    )

    assert cancelled.status == OrderStatus.CANCELLED
    assert FakeB2BClient.unreserve_calls == [_unreserve_payload(order)]


async def test_cancel_delivering_order_transitions_to_cancelled() -> None:
    user_id = uuid4()
    order = _order(user_id=user_id, status=OrderStatus.DELIVERING)
    FakeOrderRepository.orders_by_id[order.id] = order

    cancelled = await OrderService(FakeSession()).cancel_order(
        order_id=order.id,
        user_id=user_id,
    )

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
