from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.unreserve_operation import UnreserveOperation


class UnreserveOperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_order_id(self, order_id: UUID) -> UnreserveOperation | None:
        if not hasattr(self.session, "execute"):
            return None
        result = await self.session.execute(
            select(UnreserveOperation).where(UnreserveOperation.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        order_id: UUID,
        request_hash: str,
        request_payload: dict[str, object],
        response: dict[str, object],
    ) -> UnreserveOperation:
        operation = UnreserveOperation(
            order_id=order_id,
            request_hash=request_hash,
            request_payload=request_payload,
            response=response,
        )
        if not hasattr(self.session, "add"):
            return operation
        self.session.add(operation)
        await self.session.flush()
        return operation
