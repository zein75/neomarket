"""Dedicated durable recovery worker for B2C order compensation/retries."""

from __future__ import annotations

import asyncio
import logging

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.services.order_service import OrderService

logger = logging.getLogger(__name__)


async def run_once() -> None:
    async with AsyncSessionLocal() as session:
        service = OrderService(session)
        await service.retry_pending_cancellations()
        await service.retry_pending_reservation_compensations()
        await service.retry_pending_fulfillments()
        await session.commit()


async def main() -> None:
    while True:
        try:
            await run_once()
        except Exception:  # noqa: BLE001 - keep the worker alive for the next lease
            logger.exception("Failed to retry pending B2C order work")
        await asyncio.sleep(settings.recovery_worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
