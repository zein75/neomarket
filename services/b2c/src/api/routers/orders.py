from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.order import OrderResponse
from src.services.cart_service import CartService
from src.services.order_service import OrderService

router = APIRouter(tags=["orders"])


@router.get("/api/v1/orders", response_model=list[OrderResponse])
@router.get("/orders", response_model=list[OrderResponse], include_in_schema=False)
async def list_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderResponse]:
    return await OrderService(db).list_orders(current_user.id)


@router.post("/api/v1/orders", response_model=OrderResponse, status_code=201)
@router.post("/orders", response_model=OrderResponse, status_code=201, include_in_schema=False)
async def create_order(
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
    )
    await db.commit()
    return order


@router.get("/api/v1/orders/{order_id}", response_model=OrderResponse)
@router.get("/orders/{order_id}", response_model=OrderResponse, include_in_schema=False)
async def get_order(
    order_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    return await OrderService(db).get_order(order_id, current_user.id)
