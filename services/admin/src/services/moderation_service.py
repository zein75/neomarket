from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.models.moderation import ModerationStatus
from src.repositories.moderation_repo import ModerationRepository


class ModerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ModerationRepository(session)

    async def approve_product(self, card_id: UUID, moderator_id: UUID):
        card = await self.repo.get_with_skus(card_id)
        if not card:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Moderation card not found",
            )
        if card.moderator_id != moderator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Moderation card assigned to another moderator",
            )
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVE_NOT_ALLOWED",
                    "current_status": self._status_value(card.status),
                },
            )
        if not self._has_skus(card):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "APPROVE_REQUIRES_SKU"},
            )

        card.status = ModerationStatus.MODERATED
        await B2BClient().send_moderation_decision(self._moderated_event(card))
        await self.repo.session.flush()
        return card

    def _moderated_event(self, card: object) -> dict[str, object]:
        product_id = str(card.product_id)
        return {
            "idempotency_key": f"moderation-approved:{product_id}",
            "event_type": "PRODUCT_MODERATION_DECIDED",
            "product_id": product_id,
            "decision": "MODERATED",
            "status": "MODERATED",
            "hard_block": False,
            "payload": {
                "product_id": product_id,
                "status": "MODERATED",
                "decision": "MODERATED",
                "hard_block": False,
            },
        }

    def _has_skus(self, card: object) -> bool:
        if hasattr(card, "sku_ids"):
            return bool(card.sku_ids)
        return bool(getattr(card, "skus", []))

    def _status_value(self, value: object) -> str:
        return value.value if isinstance(value, ModerationStatus) else str(value)
