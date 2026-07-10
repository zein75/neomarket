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

    def __init__(self, session) -> None:
        self.session = session

    async def get_with_skus(self, card_id: UUID):
        return self.cards.get(card_id)


class FakeB2BClient:
    events: list[dict[str, object]] = []

    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeModerationRepository.cards = {}
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
