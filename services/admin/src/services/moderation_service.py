from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.audit_log import AuditLog
from src.models.processed_product_event import ProcessedProductEvent
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation import ModerationStatus
from src.repositories.moderation_repo import ModerationRepository
from src.schemas.moderation import FieldReport


class ModerationService:
    MAX_OUTBOX_ATTEMPTS = 12
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ModerationRepository(session)

    async def list_blocking_reasons(self, *, hard_block: bool | None = None):
        return await self.repo.list_all_blocking_reasons(hard_block=hard_block)

    async def list_tickets(
        self,
        *,
        limit: int,
        offset: int,
        status_filter: ModerationStatus | None = None,
    ):
        return await self.repo.list_tickets(
            limit=limit,
            offset=offset,
            status=status_filter,
        )

    async def claim_ticket(self, card_id: UUID, moderator_id: UUID):
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        last_activity = getattr(card, "updated_at", None) or getattr(card, "created_at", None)
        stale = bool(
            last_activity
            and last_activity < datetime.now(timezone.utc) - timedelta(
                seconds=settings.moderation_claim_ttl_seconds
            )
        )
        if card.moderator_id not in (None, moderator_id) and not stale:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_ALREADY_ASSIGNED", "message": "Ticket is assigned to another moderator"},
            )
        if card.status not in {ModerationStatus.CREATED, ModerationStatus.PENDING} and not stale:
            raise HTTPException(
                status_code=409,
                detail={"code": "CLAIM_NOT_ALLOWED", "message": "Ticket cannot be claimed in current status"},
            )
        card.moderator_id = moderator_id
        card.status = ModerationStatus.IN_REVIEW
        self._audit(moderator_id, "TICKET_CLAIM", card.id)
        await self.repo.session.flush()
        return card

    async def release_ticket(self, card_id: UUID, moderator_id: UUID):
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        if card.moderator_id != moderator_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_NOT_ASSIGNED", "message": "Ticket is assigned to another moderator"},
            )
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=409,
                detail={"code": "RELEASE_NOT_ALLOWED", "message": "Ticket is not in review"},
            )
        card.moderator_id = None
        card.status = ModerationStatus.PENDING
        self._audit(moderator_id, "TICKET_RELEASE", card.id)
        await self.repo.session.flush()
        return card

    async def heartbeat_ticket(self, card_id: UUID, moderator_id: UUID):
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        if card.moderator_id != moderator_id or card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_NOT_ASSIGNED", "message": "Ticket is not assigned to this moderator"},
            )
        card.updated_at = datetime.now(timezone.utc)
        self._audit(moderator_id, "TICKET_HEARTBEAT", card.id)
        await self.repo.session.flush()
        return card

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
        self._audit(moderator_id, "TICKET_APPROVE", card.id)
        await self._enqueue_decision(self._moderated_event(card))
        await self.repo.session.flush()
        return card

    async def block_product(
        self,
        card_id: UUID,
        moderator_id: UUID,
        *,
        blocking_reason_ids: list[UUID],
        comment: str | None = None,
        field_reports: list[FieldReport] | None = None,
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

        selected_reason = next(
            reason for reason in reasons if reason.id == blocking_reason_ids[0]
        )

        return await self._block_card(
            card,
            hard_block=any(reason.hard_block for reason in reasons),
            blocking_reason=selected_reason,
            comment=comment,
            field_reports=field_reports or [],
        )

    async def _block_card(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason: object | None,
        comment: str | None,
        field_reports: list[FieldReport],
    ):
        card.status = (
            ModerationStatus.HARD_BLOCKED if hard_block else ModerationStatus.BLOCKED
        )
        self._audit(getattr(card, "moderator_id", None), "TICKET_BLOCK", card.id)
        await self._enqueue_decision(
            self._blocked_event(
                card,
                hard_block=hard_block,
                blocking_reason=blocking_reason,
                comment=comment,
                field_reports=field_reports or [],
            )
        )
        await self.repo.session.flush()
        return card

    async def _enqueue_decision(self, event: dict[str, object]) -> None:
        add = getattr(self.repo.session, "add", None)
        if not callable(add):
            await B2BClient().send_moderation_decision(event)
            return
        add(
            ModerationOutboxEvent(
                idempotency_key=str(event["idempotency_key"]),
                event_type=str(event["event_type"]),
                payload=event,
            )
        )

    async def retry_pending_decisions(self, limit: int = 100) -> int:
        """Deliver committed moderation decisions; safe to run from a worker."""
        now = datetime.now(timezone.utc)
        events = await self.claim_pending_decisions(limit=limit)
        delivered = 0
        for event in events:
            event.attempts += 1
            if event.attempts > self.MAX_OUTBOX_ATTEMPTS:
                event.status = "DEAD"
                event.last_error = "OUTBOX_MAX_ATTEMPTS_EXCEEDED"
                event.lease_owner = None
                event.lease_until = None
                continue
            try:
                await B2BClient().send_moderation_decision(event.payload)
                event.status = "SENT"
                event.last_error = None
                event.next_retry_at = None
                event.lease_owner = None
                event.lease_until = None
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - retain event for retry
                event.status = "PENDING" if event.attempts == 1 else "RETRY"
                event.last_error = str(exc)[:500]
                event.next_retry_at = now + timedelta(
                    seconds=min(900, 2 ** min(event.attempts, 10))
                )
                event.lease_owner = None
                event.lease_until = None
        await self.repo.session.flush()
        return delivered

    async def claim_pending_decisions(
        self, *, worker_id: str = "admin-moderation-outbox", limit: int = 100, lease_seconds: int = 60
    ) -> list[ModerationOutboxEvent]:
        """Claim ready events with row locks so concurrent workers do not duplicate delivery."""
        if not hasattr(self.repo.session, "execute"):
            return []
        now = datetime.now(timezone.utc)
        result = await self.repo.session.execute(
            select(ModerationOutboxEvent)
            .where(
                ModerationOutboxEvent.status.in_(["PENDING", "RETRY", "LEASED"]),
                (ModerationOutboxEvent.next_retry_at.is_(None)
                 | (ModerationOutboxEvent.next_retry_at <= now)),
                (ModerationOutboxEvent.lease_until.is_(None)
                 | (ModerationOutboxEvent.lease_until < now)),
            )
            .order_by(ModerationOutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(result.scalars().all())
        lease_until = now + timedelta(seconds=lease_seconds)
        for event in events:
            event.status = "LEASED"
            event.lease_owner = worker_id
            event.lease_until = lease_until
        await self.repo.session.flush()
        return events

    async def apply_product_event(self, event: dict[str, object]) -> dict[str, str]:
        raw_event_id = str(event.get("event_id") or event.get("idempotency_key"))
        try:
            event_id = UUID(raw_event_id)
        except ValueError:
            event_id = uuid5(
                NAMESPACE_URL,
                f"admin-product-event:{raw_event_id}:{event.get('event_type')}:{event.get('product_id')}",
            )
        receipt = ProcessedProductEvent(
            event_id=event_id,
            event_type=str(event.get("event_type", "")),
            payload_sha256=hashlib.sha256(
                json.dumps(event, default=str, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        if hasattr(self.repo.session, "execute"):
            existing = await self.repo.session.execute(
                select(ProcessedProductEvent).where(ProcessedProductEvent.event_id == event_id)
            )
            stored = existing.scalar_one_or_none()
            if stored is not None:
                if stored.payload_sha256 != receipt.payload_sha256:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "EVENT_ID_CONFLICT",
                            "message": "event_id was reused with different payload",
                        },
                    )
                return {"status": "ALREADY_APPLIED"}
        add_receipt = getattr(self.repo.session, "add", None)
        if callable(add_receipt):
            add_receipt(receipt)
            try:
                await self.repo.session.flush()
            except IntegrityError:
                await self.repo.session.rollback()
                stored = await self.repo.session.scalar(
                    select(ProcessedProductEvent).where(
                        ProcessedProductEvent.event_id == receipt.event_id
                    )
                )
                if stored is not None and stored.payload_sha256 != receipt.payload_sha256:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "EVENT_ID_CONFLICT", "message": "event_id was reused with different payload"},
                    )
                return {"status": "ALREADY_APPLIED"}
        product_id = UUID(str(event["product_id"]))
        card = await self.repo.get_by_product_id(product_id)
        if not card:
            return {"status": "IGNORED"}
        event_type = str(event.get("event_type", ""))

        if event_type.endswith("DELETED"):
            self._audit(None, "PRODUCT_EVENT_DELETED", card.id)
            await self.repo.delete(card)
            return {"status": "DELETED"}
        if card.status == ModerationStatus.HARD_BLOCKED:
            return {"status": "IGNORED"}
        if event_type.endswith("EDITED"):
            self._audit(None, "PRODUCT_EVENT_EDITED", card.id)
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
            "idempotency_key": str(uuid4()),
            "event_type": "MODERATED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

    def _blocked_event(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason: object | None,
        comment: str | None,
        field_reports: list[FieldReport],
    ) -> dict[str, object]:
        product_id = str(card.product_id)
        serialized_reports = [report.model_dump(mode="json") for report in field_reports]
        return {
            # Retries reuse the same payload/key; a later decision gets a new
            # key even when it targets the same product.
            "idempotency_key": str(uuid4()),
            "event_type": "BLOCKED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "hard_block": hard_block,
            "blocking_reason_id": str(blocking_reason.id)
            if blocking_reason is not None
            else None,
            "moderator_comment": comment
            or getattr(blocking_reason, "description", None)
            or self._first_field_report_comment(serialized_reports),
            "field_reports": serialized_reports,
        }

    def _first_field_report_comment(
        self,
        field_reports: list[dict[str, object]],
    ) -> str | None:
        for report in field_reports:
            if isinstance(report, dict) and report.get("comment"):
                return str(report["comment"])
        return None

    def _has_skus(self, card: object) -> bool:
        if hasattr(card, "sku_ids"):
            return bool(card.sku_ids)
        return bool(getattr(card, "skus", []))

    def _edited_queue_priority(self, card: object) -> int:
        return max(int(getattr(card, "queue_priority", 0)), 0) + 1

    def _audit(self, actor_id: UUID | None, action: str, entity_id: UUID) -> None:
        add = getattr(self.repo.session, "add", None)
        if add is not None:
            add(
                AuditLog(
                    actor_id=actor_id,
                    action=action,
                    entity_type="moderation_ticket",
                    entity_id=entity_id,
                    details={},
                    created_at=datetime.now(timezone.utc),
                )
            )

    def _status_value(self, value: object) -> str:
        return value.value if isinstance(value, ModerationStatus) else str(value)
