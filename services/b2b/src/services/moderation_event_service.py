from fastapi import HTTPException, status
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.models.product import ProductStatus
from src.repositories.processed_event_repo import ProcessedEventRepository
from src.repositories.product_repo import ProductRepository
from src.schemas.moderation_event import ModerationDecisionEvent


class ModerationEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.product_repo = ProductRepository(session)
        self.processed_event_repo = ProcessedEventRepository(session)

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

        decision = event.event_type.value
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
            try:
                await B2CClient().send_product_blocked(product)
            except httpx.HTTPError:
                pass

        await self.product_repo.session.flush()
        return {"status": "APPLIED"}

    def _apply_moderated(self, product: object) -> None:
        product.status = ProductStatus.MODERATED
        product.is_active = True
        product.blocking_reason = None
        product.field_reports = []

    def _apply_blocked(self, product: object, event: ModerationDecisionEvent) -> None:
        product.status = (
            ProductStatus.HARD_BLOCKED if event.hard_block else ProductStatus.BLOCKED
        )
        product.is_active = False
        product.blocking_reason = (
            {"id": str(event.blocking_reason_id)} if event.blocking_reason_id else None
        )
        product.field_reports = event.field_reports
