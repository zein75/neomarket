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
        card = await self._get_mutable_card(card_id, moderator_id)
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

    async def decline_product(
        self,
        card_id: UUID,
        moderator_id: UUID,
        *,
        hard_block: bool,
        reason: dict[str, object],
        field_reports: list[dict[str, object]] | None = None,
    ):
        card = await self._get_mutable_card(card_id, moderator_id)
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DECLINE_NOT_ALLOWED",
                    "current_status": self._status_value(card.status),
                },
            )

        card.status = (
            ModerationStatus.HARD_BLOCKED if hard_block else ModerationStatus.BLOCKED
        )
        await B2BClient().send_moderation_decision(
            self._blocked_event(
                card,
                hard_block=hard_block,
                reason=reason,
                field_reports=field_reports or [],
            )
        )
        await self.repo.session.flush()
        return card

    async def apply_product_event(self, event: dict[str, object]) -> dict[str, str]:
        product_id = UUID(str(event["product_id"]))
        card = await self.repo.get_by_product_id(product_id)
        if not card:
            return {"status": "IGNORED"}
        event_type = str(event.get("event_type", ""))

        if event_type.endswith("DELETED"):
            await self.repo.delete(card)
            return {"status": "DELETED"}
        if card.status == ModerationStatus.HARD_BLOCKED:
            return {"status": "IGNORED"}
        if event_type.endswith("EDITED"):
            card.status = ModerationStatus.EDITED
            await self.repo.session.flush()
            return {"status": "UPDATED"}
        return {"status": "IGNORED"}

    async def _get_mutable_card(self, card_id: UUID, moderator_id: UUID):
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
        if card.status == ModerationStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "HARD_BLOCKED_TERMINAL",
                    "current_status": "HARD_BLOCKED",
                },
            )
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

    def _blocked_event(
        self,
        card: object,
        *,
        hard_block: bool,
        reason: dict[str, object],
        field_reports: list[dict[str, object]],
    ) -> dict[str, object]:
        product_id = str(card.product_id)
        decision = "BLOCKED"
        key_part = "hard-blocked" if hard_block else "blocked"
        return {
            "idempotency_key": f"moderation-{key_part}:{product_id}",
            "event_type": "PRODUCT_MODERATION_DECIDED",
            "product_id": product_id,
            "decision": decision,
            "status": decision,
            "hard_block": hard_block,
            "blocking_reason": reason,
            "field_reports": field_reports,
            "payload": {
                "product_id": product_id,
                "status": decision,
                "decision": decision,
                "hard_block": hard_block,
                "blocking_reason": reason,
                "field_reports": field_reports,
            },
        }

    def _has_skus(self, card: object) -> bool:
        if hasattr(card, "sku_ids"):
            return bool(card.sku_ids)
        return bool(getattr(card, "skus", []))

    def _status_value(self, value: object) -> str:
        return value.value if isinstance(value, ModerationStatus) else str(value)
