from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.order import OrderStatus
from src.models.user import User
from src.schemas.order import (
    OrderCreateRequest,
    OrderDetailResponse,
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


@router.post("/api/v1/orders", response_model=OrderResponse, status_code=201)
@router.post("/orders", response_model=OrderResponse, status_code=201, include_in_schema=False)
async def create_order(
    order_request: OrderCreateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    x_session_id: str | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    cart = await CartService(db).get_or_create_cart(
        user=current_user, session_id=x_session_id
    )
    order = await OrderService(db).checkout(
        current_user.id,
        cart.id,
        idempotency_key=idempotency_key,
        order_request=order_request,
    )
    await db.commit()
    return order


@router.get("/api/v1/orders/{id}", response_model=OrderDetailResponse)
@router.get("/orders/{id}", response_model=OrderDetailResponse, include_in_schema=False)
async def get_order(
    order_id: UUID = Path(alias="id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    return await OrderService(db).get_order(order_id, current_user.id)


@router.post("/api/v1/orders/{id}/cancel", response_model=OrderResponse)
@router.post(
    "/orders/{id}/cancel",
    response_model=OrderResponse,
    include_in_schema=False,
)
async def cancel_order(
    order_id: UUID = Path(alias="id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order = await OrderService(db).cancel_order(order_id, current_user.id)
    await db.commit()
    return order
