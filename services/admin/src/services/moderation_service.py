from datetime import datetime, timezone
from uuid import UUID
from uuid import NAMESPACE_URL, uuid5

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
                    "message": "Ticket cannot be approved in current status",
                    "current_status": self._status_value(card.status),
                },
            )
        if not self._has_skus(card):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVE_REQUIRES_SKU",
                    "message": "Ticket cannot be approved without SKU",
                },
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
                    "message": "Ticket cannot be declined in current status",
                    "current_status": self._status_value(card.status),
                },
            )

        blocking_reason_id = self._reason_id(reason)
        return await self._block_card(
            card,
            hard_block=hard_block,
            blocking_reason_id=blocking_reason_id,
            field_reports=field_reports or [],
        )

    async def block_product(
        self,
        card_id: UUID,
        moderator_id: UUID,
        *,
        blocking_reason_ids: list[UUID],
        field_reports: list[dict[str, object]] | None = None,
    ):
        card = await self._get_mutable_card(card_id, moderator_id)
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BLOCK_NOT_ALLOWED",
                    "message": "Ticket cannot be blocked in current status",
                    "current_status": self._status_value(card.status),
                },
            )

        reasons = await self.repo.list_blocking_reasons(blocking_reason_ids)
        found_ids = {reason.id for reason in reasons}
        missing_ids = [
            str(reason_id)
            for reason_id in blocking_reason_ids
            if reason_id not in found_ids
        ]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "BLOCKING_REASON_NOT_FOUND",
                    "message": "Blocking reason not found",
                    "blocking_reason_ids": missing_ids,
                },
            )

        return await self._block_card(
            card,
            hard_block=any(reason.hard_block for reason in reasons),
            blocking_reason_id=blocking_reason_ids[0],
            field_reports=field_reports or [],
        )

    async def _block_card(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason_id: UUID | None,
        field_reports: list[dict[str, object]],
    ):
        card.status = (
            ModerationStatus.HARD_BLOCKED if hard_block else ModerationStatus.BLOCKED
        )
        await B2BClient().send_moderation_decision(
            self._blocked_event(
                card,
                hard_block=hard_block,
                blocking_reason_id=blocking_reason_id,
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
            card.status = ModerationStatus.PENDING
            card.moderator_id = None
            card.queue_priority = self._edited_queue_priority(card)
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
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "TICKET_NOT_ASSIGNED",
                    "message": "Ticket is assigned to another moderator",
                },
            )
        if card.status == ModerationStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "HARD_BLOCKED_TERMINAL",
                    "message": "Hard blocked ticket cannot be modified",
                    "current_status": "HARD_BLOCKED",
                },
            )
        return card

    def _moderated_event(self, card: object) -> dict[str, object]:
        product_id = str(card.product_id)
        return {
            "idempotency_key": str(
                uuid5(NAMESPACE_URL, f"moderation:approved:{product_id}")
            ),
            "event_type": "MODERATED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

    def _blocked_event(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason_id: UUID | None,
        field_reports: list[dict[str, object]],
    ) -> dict[str, object]:
        product_id = str(card.product_id)
        key_part = "hard-blocked" if hard_block else "blocked"
        return {
            "idempotency_key": str(
                uuid5(NAMESPACE_URL, f"moderation:{key_part}:{product_id}")
            ),
            "event_type": "BLOCKED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "hard_block": hard_block,
            "blocking_reason_id": str(blocking_reason_id)
            if blocking_reason_id
            else None,
            "field_reports": field_reports,
        }

    def _reason_id(self, reason: dict[str, object]) -> UUID | None:
        raw_reason_id = reason.get("id") or reason.get("blocking_reason_id")
        if raw_reason_id is None:
            return None
        return UUID(str(raw_reason_id))

    def _has_skus(self, card: object) -> bool:
        if hasattr(card, "sku_ids"):
            return bool(card.sku_ids)
        return bool(getattr(card, "skus", []))

    def _edited_queue_priority(self, card: object) -> int:
        return max(int(getattr(card, "queue_priority", 0)), 0) + 1

    def _status_value(self, value: object) -> str:
        return value.value if isinstance(value, ModerationStatus) else str(value)
