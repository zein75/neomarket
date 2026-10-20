from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from fastapi import HTTPException

from src.api.routers import moderation as moderation_router
from src.main import app
from src.models.moderation import ModerationStatus
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.schemas.moderation import ModerationCardResponse
from src.services import moderation_service as moderation_service_module
from src.services.moderation_service import ModerationService
from src.schemas.moderation import BlockDecisionRequest
from src.schemas.admin_responses import ProductSnapshotResponse


pytestmark = pytest.mark.anyio


def test_review_checklist_exposes_product_rules_from_snapshot() -> None:
    snapshot = ProductSnapshotResponse.model_validate({
        "product_id": str(uuid4()),
        "seller_id": str(uuid4()),
        "revision": 1,
        "snapshot_hash": "a" * 64,
        "title": "Steel bottle",
        "category_id": str(uuid4()),
        "images": [{"url": "https://cdn.example.test/product.jpg"}],
        "skus": [{
            "sku_id": str(uuid4()),
            "name": "500 ml",
            "price_minor": 129900,
            "currency": "RUB",
            "images": [{"url": "https://cdn.example.test/sku.jpg"}],
        }],
        "attributes": {"volume": 500},
        "policy_version": 1,
    })
    checklist = moderation_router._review_checklist(snapshot, revision_pinned=True, published_loaded=False)
    results = {item["code"]: item["passed"] for item in checklist}
    assert results["TITLE_RULES"] is True
    assert results["CATEGORY_RULES"] is True
    assert results["SKU_RULES"] is True
    assert results["SKU_PRICE_RULES"] is True
    assert results["MEDIA_RULES"] is True


def _card(
    *,
    moderator_id: UUID,
    status: ModerationStatus = ModerationStatus.IN_REVIEW,
    sku_ids: list[UUID] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=uuid4(),
        seller_id=uuid4(),
        kind="CREATE",
        queue_priority=3,
        moderator_id=moderator_id,
        status=status,
        sku_ids=sku_ids if sku_ids is not None else [uuid4()],
        submitted_revision=1,
        snapshot_hash="a" * 64,
        version=1,
        fencing_version=0,
        lease_token_hash=None,
        lease_expires_at=None,
        updated_at=None,
        created_at="2026-10-16T00:00:00Z",
    )


class FakeSession:
    def __init__(self):
        self.flushed = False
        self.added: list[object] = []

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        return None


class FakeModerationRepository:
    cards: dict[UUID, SimpleNamespace] = {}
    blocking_reasons: dict[UUID, SimpleNamespace] = {}
    deleted_cards: list[UUID] = []

    def __init__(self, session) -> None:
        self.session = session

    async def get_with_skus(self, card_id: UUID):
        return self.cards.get(card_id)

    async def get_by_product_id(self, product_id: UUID):
        for card in self.cards.values():
            if card.product_id == product_id:
                return card
        return None

    async def get_by_product_id_for_update(self, product_id: UUID):
        return await self.get_by_product_id(product_id)

    async def delete(self, card) -> None:
        self.deleted_cards.append(card.id)
        self.cards.pop(card.id, None)

    async def list_blocking_reasons(self, reason_ids: list[UUID]):
        return [
            self.blocking_reasons[reason_id]
            for reason_id in reason_ids
            if reason_id in self.blocking_reasons
        ]

    async def list_all_blocking_reasons(self, *, hard_block: bool | None = None):
        reasons = list(self.blocking_reasons.values())
        if hard_block is not None:
            reasons = [reason for reason in reasons if reason.hard_block is hard_block]
        return reasons


class FakeB2BClient:
    events: list[dict[str, object]] = []

    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        self.events.append(event)


def test_block_decision_rejects_undeclared_field_report_fields() -> None:
    with pytest.raises(ValidationError):
        BlockDecisionRequest.model_validate(
            {
                "blocking_reason_ids": [str(uuid4())],
                "field_reports": [
                    {
                        "field_name": "description",
                        "comment": "Rewrite this text",
                        "unexpected": "not in the B2B contract",
                    }
                ],
            }
        )


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeModerationRepository.cards = {}
    FakeModerationRepository.blocking_reasons = {}
    FakeModerationRepository.deleted_cards = []
    FakeB2BClient.events = []
    monkeypatch.setattr(
        moderation_service_module,
        "ModerationRepository",
        FakeModerationRepository,
    )
    monkeypatch.setattr(moderation_service_module, "B2BClient", FakeB2BClient)


async def test_approve_transitions_to_moderated_and_emits_event() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card

    session = FakeSession()
    approved = await ModerationService(session).approve_product(
        card.id,
        moderator_id,
    )

    assert approved.status == ModerationStatus.MODERATED
    response = ModerationCardResponse.model_validate(approved).model_dump(mode="json")
    assert response["seller_id"] == str(card.seller_id)
    assert response["kind"] == "CREATE"
    assert response["priority"] == 3
    assert response["status"] == "DECISION_PENDING"
    assert response["created_at"]
    outbox = [item for item in session.added if isinstance(item, ModerationOutboxEvent)]
    assert FakeB2BClient.events == []
    assert len(outbox) == 1
    event = outbox[0].payload
    assert UUID(str(event["idempotency_key"]))
    assert event["event_type"] == "MODERATED"
    assert event["product_id"] == str(card.product_id)
    assert event["occurred_at"]
    assert "PRODUCT_MODERATION_DECIDED" not in event.values()


def test_legacy_approve_route_is_disabled() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            f"/api/v1/tickets/{card.id}/approve",
            headers={"X-Moderator-Id": str(moderator_id)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert "LEGACY_DECISION_DISABLED" in response.text
    assert FakeB2BClient.events == []


async def test_approve_others_card_returns_409() -> None:
    card = _card(moderator_id=uuid4())
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as exc:
        await ModerationService(FakeSession()).approve_product(card.id, uuid4())

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "TICKET_NOT_ASSIGNED",
        "message": "Ticket is assigned to another moderator",
    }
    assert FakeB2BClient.events == []


async def test_approve_after_edited_returns_409() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.EDITED)
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as exc:
        await ModerationService(FakeSession()).approve_product(card.id, moderator_id)

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "APPROVE_NOT_ALLOWED",
        "message": "Ticket cannot be approved in current status",
        "current_status": "EDITED",
    }
    assert FakeB2BClient.events == []


async def test_approve_without_sku_returns_409() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, sku_ids=[])
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as exc:
        await ModerationService(FakeSession()).approve_product(card.id, moderator_id)

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "APPROVE_REQUIRES_SKU",
        "message": "Ticket cannot be approved without SKU",
    }
    assert FakeB2BClient.events == []


async def test_hard_block_transitions_to_terminal_and_emits_event() -> None:
    moderator_id = uuid4()
    reason_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        title="Counterfeit product",
        description="Moderator confirmed counterfeit goods",
        hard_block=True,
    )

    session = FakeSession()
    blocked = await ModerationService(session).block_product(
        card.id,
        moderator_id,
        blocking_reason_ids=[reason_id],
    )

    assert blocked.status == ModerationStatus.HARD_BLOCKED
    assert FakeB2BClient.events == []
    event = next(item.payload for item in session.added if isinstance(item, ModerationOutboxEvent))
    assert UUID(str(event["idempotency_key"]))
    assert event["event_type"] == "BLOCKED"
    assert event["product_id"] == str(card.product_id)
    assert event["occurred_at"]
    assert event["hard_block"] is True
    assert event["blocking_reason_id"] == str(reason_id)
    assert event["moderator_comment"] == "Moderator confirmed counterfeit goods"
    assert "PRODUCT_MODERATION_DECIDED" not in event.values()


def test_legacy_block_route_is_disabled() -> None:
    moderator_id = uuid4()
    reason_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        title="Description mismatch",
        description="Default catalog reason",
        hard_block=True,
    )

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            f"/api/v1/tickets/{card.id}/block",
            json={
                "blocking_reason_ids": [str(reason_id)],
                "comment": "Photos and description contradict each other",
            },
            headers={"X-Moderator-Id": str(moderator_id)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert "LEGACY_DECISION_DISABLED" in response.text
    assert FakeB2BClient.events == []


def test_blocking_reasons_route_returns_hard_block_catalog() -> None:
    hard_reason_id = uuid4()
    soft_reason_id = uuid4()
    FakeModerationRepository.blocking_reasons[hard_reason_id] = SimpleNamespace(
        id=hard_reason_id,
        code="COUNTERFEIT_PRODUCT",
        title="Контрафактный товар",
        description=None,
        hard_block=True,
        is_active=True,
    )
    FakeModerationRepository.blocking_reasons[soft_reason_id] = SimpleNamespace(
        id=soft_reason_id,
        code="DESCRIPTION_MISMATCH",
        title="Описание не соответствует товару",
        description=None,
        hard_block=False,
        is_active=True,
    )

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).get(
            "/api/v1/blocking-reasons?hard_block=true",
            headers={"X-Moderator-Id": str(uuid4())},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "id": str(hard_reason_id),
            "code": "COUNTERFEIT_PRODUCT",
            "title": "Контрафактный товар",
            "hard_block": True,
            "is_active": True,
        }
    ]


async def test_hard_block_event_carries_hard_block_true() -> None:
    moderator_id = uuid4()
    reason_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        hard_block=True,
    )

    session = FakeSession()
    await ModerationService(session).block_product(
        card.id,
        moderator_id,
        blocking_reason_ids=[reason_id],
    )

    event = next(item.payload for item in session.added if isinstance(item, ModerationOutboxEvent))
    assert event["event_type"] == "BLOCKED"
    assert event["hard_block"] is True


async def test_any_modify_on_hard_blocked_returns_409() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.HARD_BLOCKED)
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as approve_exc:
        await ModerationService(FakeSession()).approve_product(card.id, moderator_id)
    reason_id = uuid4()
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        hard_block=True,
    )

    with pytest.raises(HTTPException) as block_exc:
        await ModerationService(FakeSession()).block_product(
            card.id,
            moderator_id,
            blocking_reason_ids=[reason_id],
        )

    assert approve_exc.value.status_code == 409
    assert block_exc.value.status_code == 409
    assert approve_exc.value.detail == {
        "code": "HARD_BLOCKED_TERMINAL",
        "message": "Hard blocked ticket cannot be modified",
        "current_status": "HARD_BLOCKED",
    }
    assert block_exc.value.detail == approve_exc.value.detail
    assert FakeB2BClient.events == []


async def test_edited_event_on_hard_blocked_is_ignored() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.HARD_BLOCKED)
    FakeModerationRepository.cards[card.id] = card

    result = await ModerationService(FakeSession()).apply_product_event(
        {
            "event_type": "PRODUCT_EDITED",
            "product_id": str(card.product_id),
            "status": "EDITED",
        }
    )

    assert result == {"status": "IGNORED"}
    assert card.status == ModerationStatus.HARD_BLOCKED


async def test_edited_event_returns_card_to_pending_queue() -> None:
    moderator_id = uuid4()
    card = _card(
        moderator_id=moderator_id,
        status=ModerationStatus.IN_REVIEW,
    )
    card.queue_priority = 2
    FakeModerationRepository.cards[card.id] = card

    result = await ModerationService(FakeSession()).apply_product_event(
        {
            "event_type": "PRODUCT_EDITED",
            "product_id": str(card.product_id),
        }
    )

    assert result == {"status": "UPDATED"}
    assert card.status == ModerationStatus.PENDING
    assert card.moderator_id is None
    assert card.queue_priority == 3


async def test_deleted_event_cancels_hard_blocked_ticket_without_erasing_history() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.HARD_BLOCKED)
    FakeModerationRepository.cards[card.id] = card

    result = await ModerationService(FakeSession()).apply_product_event(
        {
            "event_type": "PRODUCT_DELETED",
            "product_id": str(card.product_id),
        }
    )

    assert result == {"status": "CANCELLED"}
    assert FakeModerationRepository.deleted_cards == []
    assert card.id in FakeModerationRepository.cards
    assert card.status == ModerationStatus.CANCELLED


def test_product_event_route_requires_service_key() -> None:
    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/internal/v1/events/products",
            json={"event_type": "PRODUCT_EDITED", "product_id": str(uuid4())},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_product_event_route_accepts_service_key() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/events/products",
            json={"event_type": "PRODUCT_EDITED", "product_id": str(card.product_id)},
            headers={"X-Service-Key": "dev-service-key"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "UPDATED"}
    assert card.status == ModerationStatus.PENDING
    assert card.moderator_id is None
