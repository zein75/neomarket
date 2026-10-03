from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.order import OrderStatus
from src.models.user import User
from src.schemas.order import (
    OrderCreateRequest,
    CancelOrderRequest,
    OrderPaginatedResponse,
    OrderResponse,
)
from src.services.cart_service import CartService
from src.services.order_service import OrderService

router = APIRouter(tags=["orders"])


@router.get("/api/v1/orders", response_model=OrderPaginatedResponse)
@router.get("/orders", response_model=OrderPaginatedResponse, include_in_schema=False)
async def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: OrderStatus | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderPaginatedResponse:
    return await OrderService(db).list_orders(
        current_user.id,
        limit=limit,
        offset=offset,
        status_filter=status,
    )


@router.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    status_code=201,
    responses={
        200: {"model": OrderResponse, "description": "Idempotent replay"},
        400: {"description": "Invalid checkout request"},
        401: {"description": "Unauthorized"},
        409: {"description": "Reserve or idempotency conflict"},
        422: {"description": "Cart validation failed"},
        503: {"description": "B2B unavailable"},
    },
)
@router.post("/orders", response_model=OrderResponse, status_code=201, include_in_schema=False)
async def create_order(
    order_request: OrderCreateRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    x_session_id: UUID | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    key = str(idempotency_key)
    cart = await CartService(db).get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    service = OrderService(db)
    order = await service.checkout(
        current_user.id,
        cart.id,
        idempotency_key=key,
        order_request=order_request,
    )
    payload = OrderResponse.model_validate(order).model_dump(mode="json")
    return JSONResponse(
        # OpenAPI distinguishes a newly-created order from an idempotent replay.
        status_code=200 if service.last_checkout_replayed else 201,
        content=payload,
    )


@router.get("/api/v1/orders/{order_id}", response_model=OrderResponse)
@router.get("/orders/{order_id}", response_model=OrderResponse, include_in_schema=False)
async def get_order(
    order_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    return await OrderService(db).get_order(order_id, current_user.id)


@router.post(
    "/api/v1/orders/{order_id}/cancel",
    response_model=OrderResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Order not found"},
        409: {"description": "Order status does not allow cancellation"},
    },
)
@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderResponse,
    include_in_schema=False,
)
async def cancel_order(
    order_id: UUID,
    cancel_request: CancelOrderRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order = await OrderService(db).cancel_order(
        order_id,
        current_user.id,
        reason=cancel_request.reason if cancel_request else None,
    )
    return order
