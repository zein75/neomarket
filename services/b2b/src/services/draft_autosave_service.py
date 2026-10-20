from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.seller_draft_autosave import SellerDraftAutosave
from src.schemas.product import DraftAutosavePayload, DraftAutosaveResponse


class DraftAutosaveService:
    """Persists incomplete new-product form state with optimistic revisions."""

    retention = timedelta(days=30)

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, seller_id: UUID, draft_id: UUID) -> DraftAutosaveResponse:
        draft = await self.session.scalar(
            select(SellerDraftAutosave).where(
                SellerDraftAutosave.id == draft_id,
                SellerDraftAutosave.seller_id == seller_id,
            )
        )
        if draft is None or draft.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DRAFT_AUTOSAVE_NOT_FOUND", "message": "Draft autosave was not found"},
            )
        return self._response(draft)

    async def save(
        self,
        seller_id: UUID,
        draft_id: UUID,
        payload: DraftAutosavePayload,
        if_match: int | None,
    ) -> DraftAutosaveResponse:
        draft = await self.session.scalar(
            select(SellerDraftAutosave).where(
                SellerDraftAutosave.id == draft_id,
                SellerDraftAutosave.seller_id == seller_id,
            ).with_for_update()
        )
        now = datetime.now(timezone.utc)
        if draft is not None and draft.expires_at <= now:
            await self.session.delete(draft)
            await self.session.flush()
            draft = None
        if draft is None:
            if if_match not in (None, 0):
                self._raise_conflict(0)
            draft = SellerDraftAutosave(
                id=draft_id,
                seller_id=seller_id,
                revision=1,
                payload=payload.model_dump(mode="json"),
                expires_at=now + self.retention,
            )
            self.session.add(draft)
        else:
            if if_match is not None and if_match != draft.revision:
                self._raise_conflict(draft.revision)
            draft.revision += 1
            draft.payload = payload.model_dump(mode="json")
            draft.expires_at = now + self.retention
        await self.session.flush()
        return self._response(draft)

    async def delete(self, seller_id: UUID, draft_id: UUID) -> None:
        draft = await self.session.scalar(
            select(SellerDraftAutosave).where(
                SellerDraftAutosave.id == draft_id,
                SellerDraftAutosave.seller_id == seller_id,
            )
        )
        if draft is not None:
            await self.session.delete(draft)
            await self.session.flush()

    @staticmethod
    def _response(draft: SellerDraftAutosave) -> DraftAutosaveResponse:
        return DraftAutosaveResponse(
            id=draft.id,
            revision=draft.revision,
            payload=DraftAutosavePayload.model_validate(draft.payload),
            updated_at=draft.updated_at,
        )

    @staticmethod
    def _raise_conflict(server_revision: int) -> None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "PRECONDITION_FAILED",
                "message": "Draft autosave revision is stale",
                "server_revision": server_revision,
            },
        )
