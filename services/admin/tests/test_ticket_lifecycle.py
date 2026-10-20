from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.models.moderation import ModerationStatus
from src.api.routers import moderation as moderation_router
from src.services import moderation_service as moderation_module
from src.services.moderation_service import ModerationService
from src.services.product_snapshots import content_digest


class FakeSession:
    snapshot = None

    def __init__(self):
        self.scalar_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.snapshot if "moderation_snapshots" in str(_statement) else None

    def add(self, _item):
        return None

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
    _pin_snapshot(card)
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
    _pin_snapshot(card)
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
    _pin_snapshot(card)
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
            cursor="invalid",
            limit=20,
            status_filter=None,
            priority=None,
            seller_id=None,
            current_moderator=SimpleNamespace(
                id=uuid4(), permissions={"*"}, permission_scopes={}
            ),
            db=FakeSession(),
        )
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_CURSOR"


def _pin_snapshot(card):
    card.submitted_revision = 1
    card.snapshot_hash = "a" * 64
    card.version = 1
    card.fencing_version = 0
    card.lease_token_hash = None
    card.lease_expires_at = None
    content = {"product_id": str(uuid4()), "revision": 1}
    FakeSession.snapshot = SimpleNamespace(
        snapshot_hash=card.snapshot_hash,
        content=content,
        content_hash=content_digest(content),
    )
