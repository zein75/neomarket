from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_db, get_optional_user
from src.main import app
from src.services import home_service as home_service_module


class FakeSession:
    async def commit(self) -> None:
        return None


class FakeBannerRepository:
    banners: list[SimpleNamespace] = []
    events: list[dict[str, object]] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active(self, now: datetime) -> list[SimpleNamespace]:
        return sorted(
            [
                banner
                for banner in self.banners
                if banner.is_active
                and (banner.start_at is None or banner.start_at <= now)
                and (banner.end_at is None or banner.end_at >= now)
            ],
            key=lambda banner: (banner.priority, -banner.created_at.timestamp()),
        )

    async def exists(self, banner_id: UUID) -> bool:
        return any(banner.id == banner_id for banner in self.banners)

    async def create_event(self, **kwargs) -> SimpleNamespace:
        self.__class__.events.append(dict(kwargs))
        return SimpleNamespace(id=uuid4(), **kwargs)


class FakeCollectionRepository:
    collections: list[SimpleNamespace] = []
    product_ids_by_collection: dict[UUID, list[UUID]] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active(
        self,
        *,
        today: date,
        limit: int,
        offset: int,
    ) -> tuple[list[SimpleNamespace], int]:
        collections = sorted(
            [
                collection
                for collection in self.collections
                if collection.is_active
                and (collection.start_date is None or collection.start_date <= today)
            ],
            key=lambda collection: (collection.priority, -collection.created_at.timestamp()),
        )
        return collections[offset : offset + limit], len(collections)

    async def get_active(
        self,
        collection_id: UUID,
        today: date,
    ) -> SimpleNamespace | None:
        return next(
            (
                collection
                for collection in self.collections
                if collection.id == collection_id
                and collection.is_active
                and (collection.start_date is None or collection.start_date <= today)
            ),
            None,
        )

    async def list_product_ids(
        self,
        collection_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[UUID], int]:
        product_ids = self.product_ids_by_collection.get(collection_id, [])
        return product_ids[offset : offset + limit], len(product_ids)


class FakeB2BClient:
    visible_products: dict[str, dict[str, object]] = {}
    batch_calls: list[list[str]] = []

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


@pytest.fixture(autouse=True)
def patch_home(monkeypatch: pytest.MonkeyPatch):
    FakeBannerRepository.banners = []
    FakeBannerRepository.events = []
    FakeCollectionRepository.collections = []
    FakeCollectionRepository.product_ids_by_collection = {}
    FakeB2BClient.visible_products = {}
    FakeB2BClient.batch_calls = []
    monkeypatch.setattr(
        home_service_module,
        "BannerRepository",
        FakeBannerRepository,
    )
    monkeypatch.setattr(
        home_service_module,
        "CollectionRepository",
        FakeCollectionRepository,
    )
    monkeypatch.setattr(home_service_module, "B2BClient", FakeB2BClient)

    async def fake_db():
        yield FakeSession()

    async def fake_optional_user():
        return None

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_optional_user] = fake_optional_user
    yield
    app.dependency_overrides.clear()


def _banner(
    *,
    title: str,
    priority: int,
    is_active: bool = True,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        image_url=f"/cdn/banners/{title.lower().replace(' ', '-')}.jpg",
        link="/catalog",
        priority=priority,
        is_active=is_active,
        start_at=start_at,
        end_at=end_at,
        created_at=datetime.now(timezone.utc),
    )


def _collection(
    *,
    title: str,
    priority: int,
    is_active: bool = True,
    start_date: date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        description=f"{title} description",
        cover_image_url=f"/cdn/collections/{title.lower().replace(' ', '-')}.jpg",
        target_url="/collections",
        priority=priority,
        is_active=is_active,
        start_date=start_date,
        created_at=datetime.now(timezone.utc),
    )


def _product(product_id: UUID, title: str = "Keyboard") -> dict[str, object]:
    return {
        "id": str(product_id),
        "title": title,
        "description": f"{title} description",
        "images": [],
        "min_price": 1000,
    }


def test_active_banners_returned_sorted_by_priority() -> None:
    now = datetime.now(timezone.utc)
    high = _banner(
        title="High priority",
        priority=1,
        start_at=now - timedelta(days=1),
        end_at=now + timedelta(days=1),
    )
    low = _banner(title="Low priority", priority=10)
    inactive = _banner(title="Inactive", priority=0, is_active=False)
    future = _banner(
        title="Future",
        priority=0,
        start_at=now + timedelta(days=1),
    )
    expired = _banner(
        title="Expired",
        priority=0,
        end_at=now - timedelta(days=1),
    )
    FakeBannerRepository.banners = [low, inactive, future, high, expired]

    response = TestClient(app).get("/api/v1/home/banners")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert [item["id"] for item in body["items"]] == [str(high.id), str(low.id)]
    assert body["items"][0]["priority"] == 1


def test_no_active_banners_returns_200_empty() -> None:
    FakeBannerRepository.banners = [
        _banner(title="Inactive", priority=1, is_active=False)
    ]

    response = TestClient(app).get("/api/v1/home/banners")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total_count": 0}


def test_click_on_unknown_banner_returns_400() -> None:
    response = TestClient(app).post(
        "/api/v1/banner-events",
        json={"events": [{"banner_id": str(uuid4()), "event": "click"}]},
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "BANNER_NOT_FOUND",
        "message": "Banner not found",
    }
    assert FakeBannerRepository.events == []


def test_banner_event_is_recorded() -> None:
    banner = _banner(title="Promo", priority=1)
    FakeBannerRepository.banners = [banner]

    response = TestClient(app).post(
        "/api/v1/banner-events",
        json={"events": [{"banner_id": str(banner.id), "event": "impression"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert FakeBannerRepository.events[0]["banner_id"] == banner.id
    assert FakeBannerRepository.events[0]["event"] == "impression"


def test_empty_banner_events_returns_400() -> None:
    response = TestClient(app).post("/api/v1/banner-events", json={"events": []})

    assert response.status_code == 400
    assert response.json() == {
        "code": "EMPTY_EVENTS",
        "message": "Events list must not be empty",
    }


def test_collections_list_returns_metadata_without_products() -> None:
    today = date.today()
    high = _collection(title="Hits", priority=1, start_date=today)
    low = _collection(title="New season", priority=10, start_date=None)
    inactive = _collection(title="Inactive", priority=0, is_active=False)
    future = _collection(
        title="Future",
        priority=0,
        start_date=today + timedelta(days=1),
    )
    FakeCollectionRepository.collections = [low, inactive, high, future]

    response = TestClient(app).get("/api/v1/main/collections")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(high.id), str(low.id)]
    assert "items" not in body["items"][0]
    assert "products" not in body["items"][0]


def test_collection_products_enriched_from_b2b() -> None:
    collection = _collection(title="Hits", priority=1)
    product_id = uuid4()
    FakeCollectionRepository.collections = [collection]
    FakeCollectionRepository.product_ids_by_collection = {collection.id: [product_id]}
    FakeB2BClient.visible_products = {str(product_id): _product(product_id)}

    response = TestClient(app).get(f"/api/v1/collections/{collection.id}/products")

    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == str(collection.id)
    assert body["collection_title"] == "Hits"
    assert body["items"] == [_product(product_id)]
    assert body["unavailable_ids"] == []
    assert body["total_products"] == 1
    assert FakeB2BClient.batch_calls == [[str(product_id)]]


def test_unavailable_products_in_unavailable_ids() -> None:
    collection = _collection(title="Hits", priority=1)
    visible_id = uuid4()
    hidden_id = uuid4()
    FakeCollectionRepository.collections = [collection]
    FakeCollectionRepository.product_ids_by_collection = {
        collection.id: [visible_id, hidden_id]
    }
    FakeB2BClient.visible_products = {str(visible_id): _product(visible_id)}

    response = TestClient(app).get(f"/api/v1/collections/{collection.id}/products")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(visible_id)]
    assert body["unavailable_ids"] == [str(hidden_id)]
    assert body["total_products"] == 2


def test_unknown_collection_returns_404() -> None:
    response = TestClient(app).get(f"/api/v1/collections/{uuid4()}/products")

    assert response.status_code == 404
    assert response.json() == {
        "code": "COLLECTION_NOT_FOUND",
        "message": "Collection not found",
    }
