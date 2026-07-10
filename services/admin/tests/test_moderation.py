from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.models.moderation import ModerationStatus
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
        moderator_id=moderator_id,
        status=status,
        sku_ids=sku_ids if sku_ids is not None else [uuid4()],
    )


class FakeSession:
    flushed = False

    async def flush(self) -> None:
        self.flushed = True


class FakeModerationRepository:
    cards: dict[UUID, SimpleNamespace] = {}
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


class FakeB2BClient:
    events: list[dict[str, object]] = []

    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeModerationRepository.cards = {}
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
    assert FakeB2BClient.events == [
        {
            "idempotency_key": f"moderation-approved:{card.product_id}",
            "event_type": "PRODUCT_MODERATION_DECIDED",
            "product_id": str(card.product_id),
            "decision": "MODERATED",
            "status": "MODERATED",
            "hard_block": False,
            "payload": {
                "product_id": str(card.product_id),
                "status": "MODERATED",
                "decision": "MODERATED",
                "hard_block": False,
            },
        }
    ]


async def test_approve_others_card_returns_403() -> None:
    card = _card(moderator_id=uuid4())
    FakeModerationRepository.cards[card.id] = card

    with pytest.raises(HTTPException) as exc:
        await ModerationService(FakeSession()).approve_product(card.id, uuid4())

    assert exc.value.status_code == 403
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
    assert exc.value.detail == {"code": "APPROVE_REQUIRES_SKU"}
    assert FakeB2BClient.events == []


async def test_hard_block_transitions_to_terminal_and_emits_event() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card

    blocked = await ModerationService(FakeSession()).decline_product(
        card.id,
        moderator_id,
        hard_block=True,
        reason={"code": "COUNTERFEIT", "message": "Counterfeit goods"},
    )

    assert blocked.status == ModerationStatus.HARD_BLOCKED
    assert FakeB2BClient.events == [
        {
            "idempotency_key": f"moderation-hard-blocked:{card.product_id}",
            "event_type": "PRODUCT_MODERATION_DECIDED",
            "product_id": str(card.product_id),
            "decision": "BLOCKED",
            "status": "BLOCKED",
            "hard_block": True,
            "blocking_reason": {"code": "COUNTERFEIT", "message": "Counterfeit goods"},
            "field_reports": [],
            "payload": {
                "product_id": str(card.product_id),
                "status": "BLOCKED",
                "decision": "BLOCKED",
                "hard_block": True,
                "blocking_reason": {
                    "code": "COUNTERFEIT",
                    "message": "Counterfeit goods",
                },
                "field_reports": [],
            },
        }
    ]


async def test_hard_block_event_carries_hard_block_true() -> None:
    moderator_id = uuid4()
    card = _card(moderator_id=moderator_id)
    FakeModerationRepository.cards[card.id] = card

    await ModerationService(FakeSession()).decline_product(
        card.id,
        moderator_id,
        hard_block=True,
        reason={"code": "FORBIDDEN"},
    )

    assert FakeB2BClient.events[0]["decision"] == "BLOCKED"
    assert FakeB2BClient.events[0]["hard_block"] is True
    assert FakeB2BClient.events[0]["payload"]["hard_block"] is True


async def test_any_modify_on_hard_blocked_returns_403() -> None:
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

    assert approve_exc.value.status_code == 403
    assert decline_exc.value.status_code == 403
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
