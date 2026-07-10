from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.models.order import Order, OrderStatus
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
    created_orders: list[Order] = []

    def __init__(self, session) -> None:
        self.session = session

    async def get_by_idempotency_key(self, idempotency_key: str):
        return self.orders_by_key.get(idempotency_key)

    async def get_with_items(self, order_id: UUID):
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
        return order


class FakeB2BClient:
    products: list[dict[str, object]] = []
    reserve_calls: list[dict[str, object]] = []
    reserve_error: HTTPException | None = None

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


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeCartRepository.cart = None
    FakeCartRepository.removed_items = []
    FakeOrderRepository.orders_by_key = {}
    FakeOrderRepository.created_orders = []
    FakeB2BClient.products = []
    FakeB2BClient.reserve_calls = []
    FakeB2BClient.reserve_error = None
    monkeypatch.setattr(order_service_module, "CartRepository", FakeCartRepository)
    monkeypatch.setattr(order_service_module, "OrderRepository", FakeOrderRepository)
    monkeypatch.setattr(order_service_module, "B2BClient", FakeB2BClient, raising=False)


async def test_checkout_creates_paid_order_with_fixed_prices() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
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
    )

    assert order.status == OrderStatus.CONFIRMED
    assert order.total_amount == 300
    assert order.idempotency_key == "checkout-1"
    assert order.items[0].unit_price == 150
    assert order.items[0].product_title == "Phone"
    assert order.items[0].sku_name == "128 GB"
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
