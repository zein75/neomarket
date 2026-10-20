import hashlib
import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.processed_event import ProcessedB2BEvent
from src.schemas.b2b_event import ProductEventRequest
from shared.schemas.events import EventEnvelopeV1


logger = logging.getLogger(__name__)


class B2BEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle_product_event(self, event: ProductEventRequest) -> bool:
        payload_hash = self._payload_hash(event)
        processed = ProcessedB2BEvent(
            idempotency_key=event.idempotency_key,
            event=event.event.value,
            payload_hash=payload_hash,
        )
        self.session.add(processed)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            get = getattr(self.session, "get", None)
            existing = await get(ProcessedB2BEvent, event.idempotency_key) if callable(get) else None
            if existing is not None and existing.payload_hash and existing.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "EVENT_ID_CONFLICT", "message": "event id was reused with different payload"},
                )
            logger.info("Ignoring duplicate B2B event %s", event.idempotency_key)
            return False

        # Availability is computed from fresh B2B data on every cart read.
        # Persisting event-derived reasons makes a restocked/re-moderated SKU
        # permanently stale in a cart.
        return True

    async def handle_catalog_event(self, event: EventEnvelopeV1) -> bool:
        """Persist a v1 catalog envelope before any downstream application.

        Product availability is read from B2B on demand; the durable receipt is
        still required so retries and duplicate deliveries are idempotent.
        """
        payload_hash = self._payload_hash(event)
        processed = ProcessedB2BEvent(
            idempotency_key=event.event_id,
            event=event.event_type,
            payload_hash=payload_hash,
        )
        self.session.add(processed)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            get = getattr(self.session, "get", None)
            existing = await get(ProcessedB2BEvent, event.event_id) if callable(get) else None
            if existing is not None and existing.payload_hash and existing.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "EVENT_ID_CONFLICT", "message": "event id was reused with different payload"},
                )
            logger.info("Ignoring duplicate catalog event %s", event.event_id)
            return False
        return True

    async def handle_taxonomy_event(self, event: EventEnvelopeV1) -> bool:
        """Persist taxonomy receipt; B2C catalog reads canonical B2B state directly."""
        return await self.handle_catalog_event(event)

    @staticmethod
    def _payload_hash(event: object) -> str:
        payload = event.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
