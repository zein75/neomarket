import asyncio
import logging
import os

from src.core.database import AsyncSessionLocal
from src.services.taxonomy_impact_job_service import TaxonomyImpactJobService

logger = logging.getLogger(__name__)


def _poll_interval() -> float:
    try:
        value = float(os.getenv("TAXONOMY_IMPACT_POLL_INTERVAL_SECONDS", "0.5"))
    except ValueError as exc:
        raise RuntimeError("TAXONOMY_IMPACT_POLL_INTERVAL_SECONDS must be numeric") from exc
    if not 0.1 <= value <= 60:
        raise RuntimeError("TAXONOMY_IMPACT_POLL_INTERVAL_SECONDS must be between 0.1 and 60")
    return value


async def run() -> None:
    interval = _poll_interval()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                job_id = await TaxonomyImpactJobService(session).process_next()
                await session.commit()
            if job_id is None:
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Taxonomy impact worker batch failed; checkpoint is retained for retry")
            await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run())
