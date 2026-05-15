from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus


def _payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "title": "Wireless keyboard",
        "description": "Low-profile keyboard for office work",
        "category_id": str(uuid4()),
        "images": ["https://cdn.neomarket.test/products/keyboard.jpg"],
        "characteristics": {"layout": "US"},
    }
    data.update(overrides)
    return data


class FakeDB:
    async def commit(self) -> None:
        return None


async def _fake_db():
    yield FakeDB()


def _fake_seller(seller_id: UUID):
    async def dependency():
        return SimpleNamespace(id=seller_id, is_active=True)

    return dependency


class FakeProductService:
    seller_id: UUID | None = None
    data = None

    def __init__(self, db: object) -> None:
        self.db = db

    async def create(self, seller_id: UUID, data: object) -> object:
        self.__class__.seller_id = seller_id
        self.__class__.data = data
        return SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            images=data.images,
            characteristics=data.characteristics,
            status=ProductStatus.CREATED,
            category=data.category,
            is_active=False,
            skus=[],
        )


@pytest.fixture(autouse=True)
def override_dependencies(monkeypatch: pytest.MonkeyPatch):
    seller_id = uuid4()
    FakeProductService.seller_id = None
    FakeProductService.data = None
    monkeypatch.setattr(products_router, "ProductService", FakeProductService)
    app.dependency_overrides[products_router.get_current_seller] = _fake_seller(seller_id)
    app.dependency_overrides[products_router.get_db] = _fake_db
    yield seller_id
    app.dependency_overrides.clear()


def test_create_product_returns_201_with_created_status() -> None:
    response = TestClient(app).post("/api/v1/products", json=_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CREATED"
    assert body["skus"] == []


def test_seller_id_taken_from_jwt(override_dependencies: UUID) -> None:
    body_seller_id = uuid4()

    response = TestClient(app).post(
        "/api/v1/products",
        json=_payload(seller_id=str(body_seller_id)),
    )

    assert response.status_code == 201
    assert response.json()["seller_id"] == str(override_dependencies)
    assert FakeProductService.seller_id == override_dependencies


def test_missing_images_returns_400() -> None:
    payload = _payload()
    payload.pop("images")

    response = TestClient(app).post("/api/v1/products", json=payload)

    assert response.status_code == 400
    assert "images" in str(response.json()["detail"])


def test_missing_category_returns_400() -> None:
    payload = _payload()
    payload.pop("category_id")

    response = TestClient(app).post("/api/v1/products", json=payload)

    assert response.status_code == 400
    assert "category_id" in str(response.json()["detail"])


def test_invalid_category_id_returns_400() -> None:
    response = TestClient(app).post(
        "/api/v1/products", json=_payload(category_id="not-a-uuid")
    )

    assert response.status_code == 400
    assert "category_id" in str(response.json()["detail"])


def test_legacy_seller_products_endpoint_not_available() -> None:
    response = TestClient(app).post("/seller/products", json=_payload())

    assert response.status_code == 404
