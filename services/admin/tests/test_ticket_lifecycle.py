from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.models.moderation import ModerationStatus
from src.api.routers import moderation as moderation_router
from src.services import moderation_service as moderation_module
from src.services.moderation_service import ModerationService


class FakeSession:
    async def flush(self):
        return None


class FakeRepo:
    card = None

    def __init__(self, session):
        self.session = session

    async def get_with_skus_for_update(self, _card_id):
        return self.card


@pytest.mark.asyncio
async def test_claim_release_and_heartbeat(monkeypatch):
    moderator_id = uuid4()
    card = SimpleNamespace(
        id=uuid4(), moderator_id=None, status=ModerationStatus.PENDING
    )
    FakeRepo.card = card
    monkeypatch.setattr(moderation_module, "ModerationRepository", FakeRepo)
    service = ModerationService(FakeSession())

    await service.claim_ticket(card.id, moderator_id)
    assert card.moderator_id == moderator_id
    assert card.status is ModerationStatus.IN_REVIEW
    await service.heartbeat_ticket(card.id, moderator_id)
    assert card.updated_at is not None
    await service.release_ticket(card.id, moderator_id)
    assert card.moderator_id is None
    assert card.status is ModerationStatus.PENDING


@pytest.mark.asyncio
async def test_claim_rejects_other_moderator(monkeypatch):
    card = SimpleNamespace(
        id=uuid4(), moderator_id=uuid4(), status=ModerationStatus.IN_REVIEW
    )
    FakeRepo.card = card
    monkeypatch.setattr(moderation_module, "ModerationRepository", FakeRepo)

    with pytest.raises(HTTPException) as error:
        await ModerationService(FakeSession()).claim_ticket(card.id, uuid4())
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "TICKET_ALREADY_ASSIGNED"


@pytest.mark.asyncio
async def test_stale_claim_can_be_reclaimed(monkeypatch):
    card = SimpleNamespace(
        id=uuid4(),
        moderator_id=uuid4(),
        status=ModerationStatus.IN_REVIEW,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    FakeRepo.card = card
    monkeypatch.setattr(moderation_module, "ModerationRepository", FakeRepo)

    moderator_id = uuid4()
    await ModerationService(FakeSession()).claim_ticket(card.id, moderator_id)
    assert card.moderator_id == moderator_id
    assert card.status is ModerationStatus.IN_REVIEW


@pytest.mark.asyncio
async def test_ticket_list_rejects_invalid_cursor():
    with pytest.raises(HTTPException) as error:
        await moderation_router.list_tickets(
            "invalid", 20, None, SimpleNamespace(id=uuid4()), FakeSession()
        )
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_CURSOR"
