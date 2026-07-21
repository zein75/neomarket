import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.processed_event import ProcessedB2BEvent
from src.repositories.cart_repo import CartRepository
from src.schemas.b2b_event import B2BProductEvent, ProductEventRequest


logger = logging.getLogger(__name__)


class B2BEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cart_repo = CartRepository(session)

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

        await self.cart_repo.mark_skus_unavailable(
            event.sku_ids,
            self._unavailable_reason(event.event),
        )
        return True

    def _unavailable_reason(self, event: B2BProductEvent) -> str:
        if event == B2BProductEvent.SKU_OUT_OF_STOCK:
            return "OUT_OF_STOCK"
        return event.value
