import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.seller import Seller
from src.models.seller_draft_autosave import SellerDraftAutosave
from src.schemas.product import DraftAutosavePayload
from src.services.draft_autosave_service import DraftAutosaveService


class FakeSession:
    def __init__(self) -> None:
        self.draft: SellerDraftAutosave | None = None

    async def scalar(self, _statement):
        return self.draft

    def add(self, draft: SellerDraftAutosave) -> None:
        self.draft = draft

    async def flush(self) -> None:
        if self.draft is not None:
            now = datetime.now(timezone.utc)
            self.draft.created_at = self.draft.created_at or now
            self.draft.updated_at = now

    async def delete(self, _draft: SellerDraftAutosave) -> None:
        self.draft = None


def payload(title: str = "Keyboard") -> DraftAutosavePayload:
    return DraftAutosavePayload.model_validate(
        {
            "title": title,
            "description": "A recoverable draft",
            "category_id": str(uuid4()),
            "attributes": {"color": "black"},
            "currency": "RUB",
            "variants": [{"key": "variant-1", "seller_article": "KB-1"}],
            "media_names": ["keyboard.png"],
        }
    )


@pytest.mark.asyncio
async def test_autosave_creates_and_increments_revision() -> None:
    session = FakeSession()
    service = DraftAutosaveService(session)
    seller_id, draft_id = uuid4(), uuid4()

    first = await service.save(seller_id, draft_id, payload(), None)
    assert first.id == draft_id
    assert first.revision == 1
    assert first.payload.title == "Keyboard"

    second = await service.save(seller_id, draft_id, payload("Updated keyboard"), 1)
    assert second.revision == 2
    assert second.payload.title == "Updated keyboard"


@pytest.mark.asyncio
async def test_autosave_rejects_stale_revision() -> None:
    session = FakeSession()
    service = DraftAutosaveService(session)
    seller_id, draft_id = uuid4(), uuid4()
    await service.save(seller_id, draft_id, payload(), None)

    with pytest.raises(HTTPException) as error:
        await service.save(seller_id, draft_id, payload("stale"), 0)
    assert error.value.status_code == 412
    assert error.value.detail["code"] == "PRECONDITION_FAILED"


@pytest.mark.asyncio
async def test_expired_autosave_is_not_recoverable() -> None:
    session = FakeSession()
    session.draft = SellerDraftAutosave(
        id=uuid4(),
        seller_id=uuid4(),
        revision=1,
        payload=payload().model_dump(mode="json"),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(HTTPException) as error:
        await DraftAutosaveService(session).get(session.draft.seller_id, session.draft.id)
    assert error.value.status_code == 404
    assert error.value.detail["code"] == "DRAFT_AUTOSAVE_NOT_FOUND"


@pytest.mark.postgres_integration
def test_postgres_autosave_persists_revision_fence() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to an isolated migrated PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, draft_id = uuid4(), uuid4()
        email = f"autosave-{seller_id}@example.com"
        try:
            async with sessions() as session:
                session.add(
                    Seller(
                        id=seller_id,
                        email=email,
                        hashed_password="integration-only",
                        company_name="Autosave integration fixture",
                        is_active=True,
                        account_status="ACTIVE",
                    )
                )
                await session.commit()

            async with sessions() as session:
                service = DraftAutosaveService(session)
                first = await service.save(seller_id, draft_id, payload(), None)
                await session.commit()
                assert first.revision == 1

            async with sessions() as session:
                service = DraftAutosaveService(session)
                second = await service.save(seller_id, draft_id, payload("Persisted update"), 1)
                await session.commit()
                assert second.revision == 2

            async with sessions() as session:
                saved = await DraftAutosaveService(session).get(seller_id, draft_id)
                assert saved.revision == 2
                assert saved.payload.title == "Persisted update"
                with pytest.raises(HTTPException) as error:
                    await DraftAutosaveService(session).save(seller_id, draft_id, payload("stale"), 1)
                assert error.value.status_code == 412
                await DraftAutosaveService(session).delete(seller_id, draft_id)
                await session.commit()
        finally:
            async with sessions() as session:
                await session.execute(delete(SellerDraftAutosave).where(SellerDraftAutosave.seller_id == seller_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    import asyncio

    asyncio.run(scenario())
