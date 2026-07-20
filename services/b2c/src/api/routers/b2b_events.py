from fastapi import APIRouter, Depends, status

from src.api.deps import verify_service_key
from src.schemas.b2b_event import B2BEventRequest

router = APIRouter(tags=["b2b-events"])


@router.post("/api/v1/b2b/events", status_code=status.HTTP_204_NO_CONTENT)
async def receive_b2b_event(
    event: B2BEventRequest,
    _: None = Depends(verify_service_key),
) -> None:
    return None
