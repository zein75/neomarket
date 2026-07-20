from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import cart as cart_router
from src.clients import b2b_client as b2b_client_module
from src.clients.b2b_client import B2BClient
from src.main import app
from src.services import cart_service as cart_service_module
from src.services.cart_service import CartService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _cart(*, user_id: UUID | None = None, session_id: str | None = None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        session_id=session_id,
        currency="RUB",
        items=[],
    )


def _item(*, cart_id: UUID, sku_id: UUID, product_id: UUID, quantity: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        cart_id=cart_id,
        sku_id=sku_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=0,
    )


class FakeCartRepository:
    carts_by_user: dict[UUID, SimpleNamespace] = {}
    carts_by_session: dict[str, SimpleNamespace] = {}
    carts_by_id: dict[UUID, SimpleNamespace] = {}
    removed_carts: list[UUID] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: UUID):
        return self.carts_by_user.get(user_id)

    async def get_by_session_id(self, session_id: str):
        return self.carts_by_session.get(session_id)

    async def get_with_items(self, cart_id: UUID):
        return self.carts_by_id.get(cart_id)

    async def create(self, **kwargs):
        cart = _cart(
            user_id=kwargs.get("user_id"),
            session_id=kwargs.get("session_id"),
        )
        self.carts_by_id[cart.id] = cart
        if cart.user_id:
            self.carts_by_user[cart.user_id] = cart
        if cart.session_id:
            self.carts_by_session[cart.session_id] = cart
        return cart

    async def add_item(
        self,
        cart_id: UUID,
        sku_id: UUID,
        product_id: UUID,
        quantity: int,
        unit_price: int = 0,
    ):
        item = _item(
            cart_id=cart_id,
            sku_id=sku_id,
            product_id=product_id,
            quantity=quantity,
        )
        item.unit_price = unit_price
        self.carts_by_id[cart_id].items.append(item)
        return item

    async def update_item_quantity(self, item, quantity: int):
        item.quantity = quantity
        return item

    async def get_item_by_sku(self, cart_id: UUID, sku_id: UUID):
        cart = self.carts_by_id.get(cart_id)
        if not cart:
            return None
        return next((item for item in cart.items if item.sku_id == sku_id), None)

    async def remove_item(self, item) -> None:
        cart = self.carts_by_id.get(item.cart_id)
        if cart:
            cart.items.remove(item)

    async def clear_items(self, cart) -> None:
        cart.items.clear()

    async def remove_cart(self, cart) -> None:
        self.removed_carts.append(cart.id)
        self.carts_by_id.pop(cart.id, None)
        if cart.session_id:
            self.carts_by_session.pop(cart.session_id, None)


class FakeB2BClient:
    products: list[dict] = []

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_products_batch(self, product_ids: list[str]):
        return self.products

    async def get_sku(self, sku_id: str):
        for product in self.products:
            for sku in product.get("skus", []):
                if str(sku.get("id")) == sku_id:
                    return {**sku, "product_id": product["id"]}
        raise AssertionError("SKU was not found in public catalog fixture")


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    FakeCartRepository.carts_by_user = {}
    FakeCartRepository.carts_by_session = {}
    FakeCartRepository.carts_by_id = {}
    FakeCartRepository.removed_carts = []
    FakeB2BClient.products = []
    monkeypatch.setattr(cart_service_module, "CartRepository", FakeCartRepository)
    monkeypatch.setattr(cart_service_module, "B2BClient", FakeB2BClient)


@pytest.mark.asyncio
async def test_add_sku_increments_quantity_if_already_in_cart() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    item = _item(cart_id=cart.id, product_id=product_id, sku_id=sku_id, quantity=2)
    cart.items = [item]
    FakeCartRepository.carts_by_id[cart.id] = cart

    updated = await CartService(FakeSession()).add_item(
        cart.id,
        cart_service_module.CartItemAdd(sku_id=sku_id, quantity=3),
    )

    assert updated.id == item.id
    assert item.quantity == 5
    assert len(cart.items) == 1


@pytest.mark.asyncio
async def test_add_new_sku_uses_public_catalog_data() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Keyboard",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "Black",
                    "price": 12500,
                    "active_quantity": 7,
                }
            ],
        }
    ]

    added = await CartService(FakeSession()).add_item(
        cart.id,
        cart_service_module.CartItemAdd(sku_id=sku_id, quantity=2),
    )

    assert added.sku_id == sku_id
    assert added.product_id == product_id
    assert added.unit_price == 12500
    assert added.quantity == 2


@pytest.mark.asyncio
async def test_get_cart_enriched_with_b2b_data() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    cart.items = [_item(cart_id=cart.id, product_id=product_id, sku_id=sku_id, quantity=2)]
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Keyboard",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "Black",
                    "price": 12500,
                    "active_quantity": 7,
                    "images": [{"url": "https://cdn.test/sku.jpg"}],
                }
            ],
        }
    ]

    response = await CartService(FakeSession()).get_enriched_cart(cart.id)

    assert response["items"][0]["name"] == "Keyboard Black"
    assert response["items"][0]["unit_price"] == 12500
    assert response["items"][0]["line_total"] == 25000
    assert response["subtotal"] == 25000
    assert response["is_valid"] is True


@pytest.mark.asyncio
async def test_unavailable_sku_shown_with_reason() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    cart.items = [_item(cart_id=cart.id, product_id=product_id, sku_id=sku_id, quantity=2)]
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Keyboard",
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "Black",
                    "price": 12500,
                    "active_quantity": 0,
                    "images": [],
                }
            ],
        }
    ]

    response = await CartService(FakeSession()).get_enriched_cart(cart.id)

    assert response["items"][0]["is_available"] is False
    assert response["items"][0]["unavailable_reason"] == "OUT_OF_STOCK"
    assert response["items"][0]["line_total"] == 0
    assert response["subtotal"] == 0
    assert response["is_valid"] is False


@pytest.mark.asyncio
async def test_guest_cart_merged_on_login() -> None:
    user_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()
    user = SimpleNamespace(id=user_id)
    auth_cart = _cart(user_id=user_id)
    guest_cart = _cart(session_id="guest-1")
    auth_item = _item(
        cart_id=auth_cart.id,
        product_id=product_id,
        sku_id=sku_id,
        quantity=2,
    )
    guest_item = _item(
        cart_id=guest_cart.id,
        product_id=product_id,
        sku_id=sku_id,
        quantity=5,
    )
    auth_cart.items = [auth_item]
    guest_cart.items = [guest_item]
    FakeCartRepository.carts_by_user[user_id] = auth_cart
    FakeCartRepository.carts_by_session["guest-1"] = guest_cart
    FakeCartRepository.carts_by_id[auth_cart.id] = auth_cart
    FakeCartRepository.carts_by_id[guest_cart.id] = guest_cart

    merged = await CartService(FakeSession()).get_or_create_cart(
        user=user,
        session_id="guest-1",
    )

    assert merged.id == auth_cart.id
    assert auth_item.quantity == 5
    assert FakeCartRepository.removed_carts == [guest_cart.id]


def test_patch_cart_item_addresses_item_by_sku_id() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    cart.items = [_item(cart_id=cart.id, product_id=product_id, sku_id=sku_id, quantity=2)]
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeCartRepository.carts_by_session["guest-1"] = cart
    FakeB2BClient.products = [
        {
            "id": str(product_id),
            "title": "Keyboard",
            "skus": [{"id": str(sku_id), "name": "Black", "price": 12500, "active_quantity": 7}],
        }
    ]

    async def fake_db():
        yield FakeSession()

    async def fake_optional_user():
        return None

    app.dependency_overrides[cart_router.get_db] = fake_db
    app.dependency_overrides[cart_router.get_optional_user] = fake_optional_user
    try:
        response = TestClient(app).patch(
            f"/api/v1/cart/items/{sku_id}",
            json={"quantity": 4},
            headers={"X-Session-Id": "guest-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["sku_id"] == str(sku_id)
    assert response.json()["items"][0]["quantity"] == 4


def test_delete_cart_item_addresses_item_by_sku_id() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    sku_id = uuid4()
    item = _item(cart_id=cart.id, product_id=product_id, sku_id=sku_id, quantity=2)
    cart.items = [item]
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeCartRepository.carts_by_session["guest-1"] = cart

    async def fake_db():
        yield FakeSession()

    async def fake_optional_user():
        return None

    app.dependency_overrides[cart_router.get_db] = fake_db
    app.dependency_overrides[cart_router.get_optional_user] = fake_optional_user
    try:
        response = TestClient(app).delete(
            f"/api/v1/cart/items/{sku_id}",
            headers={"X-Session-Id": "guest-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert cart.items == []


def test_clear_cart_returns_204_and_removes_all_items() -> None:
    cart = _cart(session_id="guest-1")
    product_id = uuid4()
    cart.items = [
        _item(cart_id=cart.id, product_id=product_id, sku_id=uuid4(), quantity=2),
        _item(cart_id=cart.id, product_id=product_id, sku_id=uuid4(), quantity=1),
    ]
    FakeCartRepository.carts_by_id[cart.id] = cart
    FakeCartRepository.carts_by_session["guest-1"] = cart

    async def fake_db():
        yield FakeSession()

    async def fake_optional_user():
        return None

    app.dependency_overrides[cart_router.get_db] = fake_db
    app.dependency_overrides[cart_router.get_optional_user] = fake_optional_user
    try:
        response = TestClient(app).delete(
            "/api/v1/cart",
            headers={"X-Session-Id": "guest-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert cart.items == []


@pytest.mark.asyncio
async def test_b2b_client_get_sku_uses_public_sku_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sku_id = uuid4()
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"id": str(sku_id), "product_id": str(uuid4())}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def get(self, path: str, *, headers=None, **kwargs):
            captured["path"] = path
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(b2b_client_module.httpx, "AsyncClient", FakeAsyncClient)

    async with B2BClient("http://b2b") as client:
        await client.get_sku(str(sku_id))

    assert captured["path"] == f"/api/v1/public/skus/{sku_id}"
    assert captured["headers"] == {
        "X-Service-Key": "dev-service-key-change-in-production"
    }
