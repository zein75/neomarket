from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def patch_home(monkeypatch: pytest.MonkeyPatch):
    FakeBannerRepository.banners = []
    FakeBannerRepository.events = []
    monkeypatch.setattr(
        home_service_module,
        "BannerRepository",
        FakeBannerRepository,
    )

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
