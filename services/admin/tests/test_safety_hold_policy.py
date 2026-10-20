from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.routers import products
from src.core.config import settings
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.schemas.products import HoldInput


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return None

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


class FakeB2BClient:
    calls = 0
    product_id = None

    async def get_internal_json(self, path):
        type(self).calls += 1
        assert path == f"/internal/v1/products/{self.product_id}/publication"
        return {
            "product_id": str(self.product_id),
            "current_revision": 7,
            "published_revision": 6,
            "visible": True,
            "visibility_reasons": [],
        }


def _request():
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/admin/v1/products/test/safety-hold",
        "raw_path": b"/admin/v1/products/test/safety-hold",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 443),
        "path_params": {},
        "state": {"request_id": "req-test"},
        "app": None,
    })


def _hold(*, hours: int = 0, minutes: int = 0) -> HoldInput:
    return HoldInput(
        reason_code="SAFETY_REVIEW",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes),
        comment="Risk report",
    )


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    FakeB2BClient.calls = 0
    monkeypatch.setattr(products, "B2BClient", FakeB2BClient)


@pytest.mark.asyncio
async def test_short_hold_is_queued_with_revision_bound_outbox(monkeypatch):
    monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 3600)
    product_id = uuid4()
    FakeB2BClient.product_id = product_id
    actor = SimpleNamespace(id=uuid4())
    db = FakeSession()

    response = await products.request_product_safety_hold(
        product_id,
        _hold(minutes=5),
        _request(),
        '"v7"',
        uuid4(),
        actor,
        db,
    )

    operation = next(item for item in db.added if isinstance(item, AdminOperation))
    outbox = next(item for item in db.added if isinstance(item, ModerationOutboxEvent))
    audit = next(item for item in db.added if isinstance(item, AuditLog))
    assert response.status == "QUEUED"
    assert operation.status == "QUEUED"
    assert operation.payload["expected_version"] == 7
    assert outbox.payload["command"]["expected_version"] == 7
    assert outbox.payload["command"]["command_type"] == "PRODUCT_SAFETY_HOLD"
    assert audit.details["maker_checker_required"] is False
    assert db.commits == 2


@pytest.mark.asyncio
async def test_long_hold_waits_for_independent_approval_without_outbox(monkeypatch):
    monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 3600)
    product_id = uuid4()
    FakeB2BClient.product_id = product_id
    db = FakeSession()

    response = await products.request_product_safety_hold(
        product_id,
        _hold(hours=2),
        _request(),
        '"v7"',
        uuid4(),
        SimpleNamespace(id=uuid4()),
        db,
    )

    operation = next(item for item in db.added if isinstance(item, AdminOperation))
    assert response.status == "WAITING_APPROVAL"
    assert operation.status == "WAITING_APPROVAL"
    assert not any(isinstance(item, ModerationOutboxEvent) for item in db.added)
    assert FakeB2BClient.calls == 1


@pytest.mark.asyncio
async def test_missing_hold_policy_fails_before_external_lookup_or_writes(monkeypatch):
    monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", None)
    product_id = uuid4()
    FakeB2BClient.product_id = product_id
    db = FakeSession()

    with pytest.raises(HTTPException) as error:
        await products.request_product_safety_hold(
            product_id,
            _hold(hours=1),
            _request(),
            '"v7"',
            uuid4(),
            SimpleNamespace(id=uuid4()),
            db,
        )

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "SAFETY_HOLD_POLICY_NOT_CONFIGURED"
    assert db.added == []
    assert db.commits == 0
    assert FakeB2BClient.calls == 0
