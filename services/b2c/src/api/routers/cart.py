from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_optional_user
from src.models.user import User
from src.schemas.cart import CartItemAdd, CartItemResponse, CartItemUpdate, CartResponse
from src.services.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["cart"])


@router.get("", response_model=CartResponse)
async def get_cart(
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CartResponse:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    await db.commit()
    cart = await svc.get_cart_with_items(cart.id)
    return cart


@router.post("/items", response_model=CartItemResponse, status_code=201)
async def add_item(
    data: CartItemAdd,
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CartItemResponse:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    item = await svc.add_item(cart.id, data)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/items/{item_id}", response_model=CartItemResponse)
async def update_item(
    item_id: UUID,
    data: CartItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> CartItemResponse:
    svc = CartService(db)
    item = await svc.update_item(item_id, data)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/items/{item_id}", status_code=204)
async def remove_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = CartService(db)
    await svc.remove_item(item_id)
    await db.commit()
