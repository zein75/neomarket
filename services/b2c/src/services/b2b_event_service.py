import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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

        # Availability is computed from fresh B2B data on every cart read.
        # Persisting event-derived reasons makes a restocked/re-moderated SKU
        # permanently stale in a cart.
        return True
