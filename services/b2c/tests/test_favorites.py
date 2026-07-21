from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.deps import get_current_user, get_db
from src.main import app
from src.services import favorite_service as favorite_service_module


class FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeFavoriteRepository:
    favorites: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_by_user(self, user_id: UUID) -> list[SimpleNamespace]:
        return [
            favorite
            for favorite in self.favorites
            if favorite.user_id == user_id
        ]

    async def get_by_user_and_product(
        self,
        user_id: UUID,
        product_id: UUID,
    ) -> SimpleNamespace | None:
        return next(
            (
                favorite
                for favorite in self.favorites
                if favorite.user_id == user_id and favorite.product_id == product_id
            ),
            None,
        )

    async def create(self, **kwargs) -> SimpleNamespace:
        favorite = SimpleNamespace(
            id=uuid4(),
            user_id=kwargs["user_id"],
            product_id=kwargs["product_id"],
            added_at=datetime.now(timezone.utc),
            product=None,
        )
        self.favorites.append(favorite)
        return favorite

    async def delete(self, favorite: SimpleNamespace) -> None:
        self.favorites = [item for item in self.favorites if item.id != favorite.id]
        self.__class__.favorites = self.favorites


class FakeProductSubscriptionRepository:
    subscriptions: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_by_user_and_product(
        self,
        user_id: UUID,
        product_id: UUID,
    ) -> SimpleNamespace | None:
        return next(
            (
                subscription
                for subscription in self.subscriptions
                if subscription.user_id == user_id
                and subscription.product_id == product_id
            ),
            None,
        )

    async def create(self, **kwargs) -> SimpleNamespace:
        subscription = SimpleNamespace(
            id=uuid4(),
            user_id=kwargs["user_id"],
            product_id=kwargs["product_id"],
            notify_on=kwargs["notify_on"],
            created_at=datetime.now(timezone.utc),
        )
        self.subscriptions.append(subscription)
        return subscription

    async def delete(self, subscription: SimpleNamespace) -> None:
        self.subscriptions = [
            item for item in self.subscriptions if item.id != subscription.id
        ]
        self.__class__.subscriptions = self.subscriptions


class FakeB2BClient:
    visible_products: dict[str, dict[str, object]] = {}
    batch_calls: list[list[str]] = []
    product_calls: list[str] = []

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get_products_batch(self, product_ids: list[str]):
        self.__class__.batch_calls.append(product_ids)
        return [
            self.visible_products[product_id]
            for product_id in product_ids
            if product_id in self.visible_products
        ]

    async def get_product(self, product_id: str):
        self.__class__.product_calls.append(product_id)
        if product_id not in self.visible_products:
            raise HTTPException(status_code=404, detail="Product not found")
        return self.visible_products[product_id]


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id=uuid4())
    FakeFavoriteRepository.favorites = []
    FakeProductSubscriptionRepository.subscriptions = []
    FakeB2BClient.visible_products = {}
    FakeB2BClient.batch_calls = []
    FakeB2BClient.product_calls = []
    monkeypatch.setattr(
        favorite_service_module,
        "FavoriteRepository",
        FakeFavoriteRepository,
    )
    monkeypatch.setattr(
        favorite_service_module,
        "ProductSubscriptionRepository",
        FakeProductSubscriptionRepository,
    )
    monkeypatch.setattr(favorite_service_module, "B2BClient", FakeB2BClient)

    async def fake_db():
        yield FakeSession()

    async def fake_user():
        return user

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    yield user
    app.dependency_overrides.clear()


def _product(product_id: UUID, title: str = "Keyboard") -> dict[str, object]:
    return {
        "id": str(product_id),
        "title": title,
        "description": f"{title} description",
        "category_id": str(uuid4()),
        "images": [],
        "min_price": 1000,
    }


def test_add_to_favorites_returns_201(patch_dependencies: SimpleNamespace) -> None:
    product_id = uuid4()

    response = TestClient(app).post(
        "/api/v1/favorites",
        json={"product_id": str(product_id)},
    )

    assert response.status_code == 201
    assert response.json()["product_id"] == str(product_id)
    assert len(FakeFavoriteRepository.favorites) == 1
    assert FakeFavoriteRepository.favorites[0].user_id == patch_dependencies.id


def test_repeat_add_returns_200_not_duplicate(
    patch_dependencies: SimpleNamespace,
) -> None:
    product_id = uuid4()
    client = TestClient(app)

    first = client.post("/api/v1/favorites", json={"product_id": str(product_id)})
    second = client.post("/api/v1/favorites", json={"product_id": str(product_id)})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["product_id"] == str(product_id)
    assert len(FakeFavoriteRepository.favorites) == 1
    assert FakeFavoriteRepository.favorites[0].user_id == patch_dependencies.id


def test_get_favorites_enriched_from_b2b(
    patch_dependencies: SimpleNamespace,
) -> None:
    product_id = uuid4()
    FakeFavoriteRepository.favorites = [
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=product_id,
            added_at=datetime.now(timezone.utc),
        )
    ]
    product = _product(product_id)
    FakeB2BClient.visible_products = {str(product_id): product}

    response = TestClient(app).get("/api/v1/favorites")

    assert response.status_code == 200
    assert response.json()[0]["product"] == product
    assert FakeB2BClient.batch_calls == [[str(product_id)]]


def test_blocked_product_excluded_from_list(
    patch_dependencies: SimpleNamespace,
) -> None:
    visible_product_id = uuid4()
    blocked_product_id = uuid4()
    FakeFavoriteRepository.favorites = [
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=visible_product_id,
            added_at=datetime.now(timezone.utc),
        ),
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=blocked_product_id,
            added_at=datetime.now(timezone.utc),
        ),
    ]
    FakeB2BClient.visible_products = {
        str(visible_product_id): _product(visible_product_id)
    }

    response = TestClient(app).get("/api/v1/favorites")

    assert response.status_code == 200
    assert [item["product_id"] for item in response.json()] == [str(visible_product_id)]


def test_user_id_from_query_is_ignored(
    patch_dependencies: SimpleNamespace,
) -> None:
    own_product_id = uuid4()
    other_product_id = uuid4()
    other_user_id = uuid4()
    FakeFavoriteRepository.favorites = [
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=own_product_id,
            added_at=datetime.now(timezone.utc),
        ),
        SimpleNamespace(
            id=uuid4(),
            user_id=other_user_id,
            product_id=other_product_id,
            added_at=datetime.now(timezone.utc),
        ),
    ]
    FakeB2BClient.visible_products = {
        str(own_product_id): _product(own_product_id, "Own product"),
        str(other_product_id): _product(other_product_id, "Other product"),
    }

    response = TestClient(app).get(
        "/api/v1/favorites",
        params={"user_id": str(other_user_id)},
    )

    assert response.status_code == 200
    assert [item["product_id"] for item in response.json()] == [str(own_product_id)]


def test_delete_missing_favorite_returns_204() -> None:
    response = TestClient(app).delete(f"/api/v1/favorites/{uuid4()}")

    assert response.status_code == 204


def test_subscribe_returns_201_with_notify_on(
    patch_dependencies: SimpleNamespace,
) -> None:
    product_id = uuid4()
    FakeB2BClient.visible_products = {str(product_id): _product(product_id)}

    response = TestClient(app).post(
        f"/api/v1/favorites/{product_id}/subscribe",
        json={"notify_on": ["IN_STOCK", "PRICE_DOWN"]},
    )

    assert response.status_code == 201
    assert response.json()["product_id"] == str(product_id)
    assert response.json()["notify_on"] == ["IN_STOCK", "PRICE_DOWN"]
    assert len(FakeProductSubscriptionRepository.subscriptions) == 1
    assert (
        FakeProductSubscriptionRepository.subscriptions[0].user_id
        == patch_dependencies.id
    )
    assert FakeB2BClient.product_calls == [str(product_id)]


def test_duplicate_subscription_returns_409(
    patch_dependencies: SimpleNamespace,
) -> None:
    product_id = uuid4()
    FakeProductSubscriptionRepository.subscriptions = [
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=product_id,
            notify_on=["IN_STOCK"],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = TestClient(app).post(
        f"/api/v1/favorites/{product_id}/subscribe",
        json={"notify_on": ["IN_STOCK"]},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "SUBSCRIPTION_ALREADY_EXISTS",
        "message": "Subscription already exists",
    }
    assert FakeB2BClient.product_calls == []


def test_invalid_notify_on_returns_400() -> None:
    product_id = uuid4()
    client = TestClient(app)

    empty_response = client.post(
        f"/api/v1/favorites/{product_id}/subscribe",
        json={"notify_on": []},
    )
    invalid_response = client.post(
        f"/api/v1/favorites/{product_id}/subscribe",
        json={"notify_on": ["IN_STOCK", "EMAIL_ME"]},
    )

    assert empty_response.status_code == 400
    assert empty_response.json()["code"] == "INVALID_NOTIFY_ON"
    assert invalid_response.status_code == 400
    assert invalid_response.json()["code"] == "INVALID_NOTIFY_ON"
    assert FakeProductSubscriptionRepository.subscriptions == []


def test_subscribe_to_unknown_product_returns_404() -> None:
    product_id = uuid4()

    response = TestClient(app).post(
        f"/api/v1/favorites/{product_id}/subscribe",
        json={"notify_on": ["IN_STOCK"]},
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Product not found",
    }
    assert FakeProductSubscriptionRepository.subscriptions == []


def test_unsubscribe_returns_204(
    patch_dependencies: SimpleNamespace,
) -> None:
    product_id = uuid4()
    FakeProductSubscriptionRepository.subscriptions = [
        SimpleNamespace(
            id=uuid4(),
            user_id=patch_dependencies.id,
            product_id=product_id,
            notify_on=["IN_STOCK"],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = TestClient(app).delete(
        f"/api/v1/favorites/{product_id}/subscribe",
    )

    assert response.status_code == 204
    assert FakeProductSubscriptionRepository.subscriptions == []
