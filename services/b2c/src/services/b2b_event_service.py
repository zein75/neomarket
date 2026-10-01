import logging

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cart import CartItem
from src.models.processed_event import ProcessedB2BEvent
from src.schemas.b2b_event import ProductEventRequest


logger = logging.getLogger(__name__)


class B2BEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle_product_event(self, event: ProductEventRequest) -> bool:
        processed = ProcessedB2BEvent(
            idempotency_key=event.idempotency_key,
            event=event.event.value,
        )
        self.session.add(processed)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            logger.info("Ignoring duplicate B2B event %s", event.idempotency_key)
            return False

        await self._mark_cart_items_unavailable(event)
        return True

    async def _mark_cart_items_unavailable(self, event: ProductEventRequest) -> None:
        reason = {
            "PRODUCT_BLOCKED": "PRODUCT_BLOCKED",
            "PRODUCT_DELETED": "PRODUCT_DELETED",
            "SKU_OUT_OF_STOCK": "OUT_OF_STOCK",
        }[event.event.value]
        if not event.sku_ids:
            return
        await self.session.execute(
            update(CartItem)
            .where(CartItem.sku_id.in_(event.sku_ids))
            .values(unavailable_reason=reason)
        )
