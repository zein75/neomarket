from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.b2b_event import (
    LegacyB2BEventRequest,
    ProductEventRequest,
    ProductEventResponse,
)
from src.services.b2b_event_service import B2BEventService

router = APIRouter(tags=["b2b-events"])


@router.post("/api/v1/events/product", response_model=ProductEventResponse)
async def receive_product_event(
    event: ProductEventRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> ProductEventResponse:
    await B2BEventService(db).handle_product_event(event)
    await db.commit()
    return ProductEventResponse(accepted=True)


@router.post("/api/v1/b2b/events", status_code=status.HTTP_204_NO_CONTENT)
async def receive_b2b_event(
    event: LegacyB2BEventRequest,
    _: None = Depends(verify_service_key),
) -> None:
    return None
