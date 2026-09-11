from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

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


@router.post(
    "/api/v1/b2b/events",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def receive_b2b_event(
    event: LegacyB2BEventRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> None:
    payload = dict(event.payload)
    product_event = ProductEventRequest.model_validate(
        {
            "event": event.event_type,
            "idempotency_key": event.idempotency_key,
            "product_id": payload.get("product_id") or UUID(int=0),
            "sku_ids": payload.get("sku_ids")
            or ([payload["sku_id"]] if payload.get("sku_id") else []),
            "reason": payload.get("reason"),
            "date": event.occurred_at,
        }
    )
    await B2BEventService(db).handle_product_event(product_event)
    await db.commit()
