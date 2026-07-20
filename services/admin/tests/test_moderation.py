from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from src.api.routers import moderation as moderation_router
from src.main import app
from src.models.moderation import ModerationStatus
from src.schemas.moderation import ModerationCardResponse
from src.services import moderation_service as moderation_service_module
from src.services.moderation_service import ModerationService


pytestmark = pytest.mark.anyio


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
        kind="PRODUCT",
        queue_priority=0,
        moderator_id=moderator_id,
        status=status,
        sku_ids=sku_ids if sku_ids is not None else [uuid4()],
    )


class FakeSession:
    flushed = False

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

    async def delete(self, card) -> None:
        self.deleted_cards.append(card.id)
        self.cards.pop(card.id, None)

    async def list_blocking_reasons(self, reason_ids: list[UUID]):
        return [
            self.blocking_reasons[reason_id]
            for reason_id in reason_ids
            if reason_id in self.blocking_reasons
        ]


class FakeB2BClient:
    events: list[dict[str, object]] = []

    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        self.events.append(event)


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

    approved = await ModerationService(FakeSession()).approve_product(
        card.id,
        moderator_id,
    )

    assert approved.status == ModerationStatus.MODERATED
    response = ModerationCardResponse.model_validate(approved).model_dump(mode="json")
    assert response["seller_id"] == str(card.seller_id)
    assert response["kind"] == "PRODUCT"
    assert response["queue_priority"] == 0
    assert response["status"] == "APPROVED"
    assert response["created_at"]
    assert len(FakeB2BClient.events) == 1
    event = FakeB2BClient.events[0]
    assert UUID(str(event["idempotency_key"]))
    assert event["event_type"] == "MODERATED"
    assert event["product_id"] == str(card.product_id)
    assert event["occurred_at"]
    assert "PRODUCT_MODERATION_DECIDED" not in event.values()


def test_approve_ticket_route_returns_contract_response() -> None:
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

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(card.id)
    assert body["product_id"] == str(card.product_id)
    assert body["seller_id"] == str(card.seller_id)
    assert body["kind"] == "PRODUCT"
    assert body["queue_priority"] == 0
    assert body["status"] == "APPROVED"
    assert body["created_at"]


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
        hard_block=True,
    )

    blocked = await ModerationService(FakeSession()).block_product(
        card.id,
        moderator_id,
        blocking_reason_ids=[reason_id],
    )

    assert blocked.status == ModerationStatus.HARD_BLOCKED
    assert len(FakeB2BClient.events) == 1
    event = FakeB2BClient.events[0]
    assert UUID(str(event["idempotency_key"]))
    assert event["event_type"] == "BLOCKED"
    assert event["product_id"] == str(card.product_id)
    assert event["occurred_at"]
    assert event["hard_block"] is True
    assert event["blocking_reason_id"] == str(reason_id)
    assert "blocking_reason" not in event
    assert "PRODUCT_MODERATION_DECIDED" not in event.values()


def test_block_ticket_route_returns_contract_response_and_emits_event() -> None:
    moderator_id = uuid4()
    reason_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        hard_block=True,
    )

    async def fake_db():
        yield FakeSession()

    app.dependency_overrides[moderation_router.get_db] = fake_db
    try:
        response = TestClient(app).post(
            f"/api/v1/tickets/{card.id}/block",
            json={"blocking_reason_ids": [str(reason_id)]},
            headers={"X-Moderator-Id": str(moderator_id)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(card.id)
    assert body["seller_id"] == str(card.seller_id)
    assert body["kind"] == "PRODUCT"
    assert body["queue_priority"] == 0
    assert body["status"] == "REJECTED"
    assert body["created_at"]
    assert FakeB2BClient.events[0]["event_type"] == "BLOCKED"
    assert FakeB2BClient.events[0]["blocking_reason_id"] == str(reason_id)


async def test_hard_block_event_carries_hard_block_true() -> None:
    moderator_id = uuid4()
    reason_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card
    FakeModerationRepository.blocking_reasons[reason_id] = SimpleNamespace(
        id=reason_id,
        hard_block=True,
    )

    await ModerationService(FakeSession()).block_product(
        card.id,
        moderator_id,
        blocking_reason_ids=[reason_id],
    )

    assert FakeB2BClient.events[0]["event_type"] == "BLOCKED"
    assert FakeB2BClient.events[0]["hard_block"] is True
    assert FakeB2BClient.events[0]["blocking_reason_id"] == str(reason_id)


async def test_any_modify_on_hard_blocked_returns_409() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.HARD_BLOCKED)
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as approve_exc:
        await ModerationService(FakeSession()).approve_product(card.id, moderator_id)
    with pytest.raises(HTTPException) as decline_exc:
        await ModerationService(FakeSession()).decline_product(
            card.id,
            moderator_id,
            hard_block=True,
            reason={"code": "FORBIDDEN"},
        )

    assert approve_exc.value.status_code == 409
    assert decline_exc.value.status_code == 409
    assert approve_exc.value.detail == {
        "code": "HARD_BLOCKED_TERMINAL",
        "message": "Hard blocked ticket cannot be modified",
        "current_status": "HARD_BLOCKED",
    }
    assert decline_exc.value.detail == approve_exc.value.detail
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


async def test_deleted_event_removes_hard_blocked() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id, status=ModerationStatus.HARD_BLOCKED)
    FakeModerationRepository.cards[card.id] = card

    result = await ModerationService(FakeSession()).apply_product_event(
        {
            "event_type": "PRODUCT_DELETED",
            "product_id": str(card.product_id),
        }
    )

    assert result == {"status": "DELETED"}
    assert FakeModerationRepository.deleted_cards == [card.id]
    assert card.id not in FakeModerationRepository.cards


def test_product_event_route_requires_service_key() -> None:
    response = TestClient(app).post(
        "/api/v1/events/products",
        json={"event_type": "PRODUCT_EDITED", "product_id": str(uuid4())},
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "UNAUTHORIZED",
        "message": "Invalid service key",
    }


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
