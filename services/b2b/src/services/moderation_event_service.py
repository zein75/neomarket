from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import ProductStatus
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.repositories.processed_event_repo import ProcessedEventRepository
from src.repositories.product_repo import ProductRepository
from src.schemas.moderation_event import ModerationDecisionEvent


class ModerationEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.product_repo = ProductRepository(session)
        self.processed_event_repo = ProcessedEventRepository(session)
        self.outbox_repo = OutboxEventRepository(session)

    async def apply(self, event: ModerationDecisionEvent) -> dict[str, str]:
        idempotency_key = str(event.idempotency_key)
        if await self.processed_event_repo.exists(idempotency_key):
            return {"status": "DUPLICATE"}
        product = await self.product_repo.get_with_skus(event.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found",
                },
            )

        decision = event.status.value
        if decision not in {
            ProductStatus.MODERATED.value,
            ProductStatus.BLOCKED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Unsupported moderation decision",
                },
            )

        try:
            await self.processed_event_repo.mark_processed(idempotency_key)
        except IntegrityError:
            rollback = getattr(self.processed_event_repo.session, "rollback", None)
            if rollback:
                await rollback()
            return {"status": "DUPLICATE"}

        if decision == ProductStatus.MODERATED.value:
            self._apply_moderated(product)
        else:
            self._apply_blocked(product, event)
            await self.outbox_repo.create_b2c_event(
                idempotency_key=idempotency_key,
                event_type="PRODUCT_BLOCKED",
                payload={
                    "event_type": "PRODUCT_BLOCKED",
                    "idempotency_key": idempotency_key,
                    "occurred_at": event.occurred_at.isoformat(),
                    "payload": {
                        "product_id": str(product.id),
                        "sku_ids": [str(sku.id) for sku in product.skus],
                        "reason": product.status.value,
                    },
                },
            )

        await self.product_repo.session.flush()
        return {"status": "APPLIED"}

    def _apply_moderated(self, product: object) -> None:
        product.status = ProductStatus.MODERATED
        product.is_active = True
        product.blocking_reason = None
        product.field_reports = []

    def _apply_blocked(self, product: object, event: ModerationDecisionEvent) -> None:
        product.status = (
            ProductStatus.HARD_BLOCKED if event.hard_block is True else ProductStatus.BLOCKED
        )
        product.is_active = False
        product.blocking_reason = self._blocking_reason_payload(event)
        product.field_reports = [
            report.model_dump(mode="json") for report in (event.field_reports or [])
        ]

    def _blocking_reason_payload(
        self,
        event: ModerationDecisionEvent,
    ) -> dict[str, str] | None:
        if event.blocking_reason is None:
            return None
        return {
            "id": str(event.blocking_reason.id),
            "title": event.blocking_reason.title,
            "comment": event.blocking_reason.comment,
        }

    def _first_field_report_comment(
        self,
        event: ModerationDecisionEvent,
    ) -> str | None:
        for report in event.field_reports:
            if report.comment:
                return report.comment
        return None
