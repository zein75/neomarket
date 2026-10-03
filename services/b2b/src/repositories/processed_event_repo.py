from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.processed_event import ProcessedEvent
from .base import BaseRepository


class ProcessedEventRepository(BaseRepository[ProcessedEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProcessedEvent)

    async def exists(self, idempotency_key: str) -> bool:
        result = await self.session.execute(
            select(ProcessedEvent.id).where(
                ProcessedEvent.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none() is not None

    async def mark_processed(self, idempotency_key: str) -> None:
        self.session.add(ProcessedEvent(idempotency_key=idempotency_key))
        await self.session.flush()
