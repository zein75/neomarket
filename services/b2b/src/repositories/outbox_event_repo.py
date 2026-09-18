from typing import Any
from sqlalchemy import select

from src.models.outbox_event import OutboxEvent
from .base import BaseRepository


class OutboxEventRepository(BaseRepository[OutboxEvent]):
    def __init__(self, session: Any) -> None:
        super().__init__(session, OutboxEvent)

    async def get_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None:
        if not hasattr(self.session, "execute"):
            return None
        result = await self.session.execute(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def create_b2c_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxEvent | None:
        # Test doubles without a persistence API still exercise reservation logic.
        if not hasattr(self.session, "add"):
            return None
        if await self.get_by_idempotency_key(idempotency_key):
            return None
        event = OutboxEvent(
            destination="B2C",
            event_type=event_type,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event
