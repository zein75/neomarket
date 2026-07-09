from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_optional_user
from src.models.user import User
from src.schemas.cart import CartItemAdd, CartItemUpdate, CartResponse
from src.services.cart_service import CartService

router = APIRouter(tags=["cart"])


async def _get_cart_response(
    *,
    x_session_id: str | None,
    current_user: User | None,
    db: AsyncSession,
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.get("/api/v1/cart", response_model=CartResponse)
@router.get("/cart", response_model=CartResponse, include_in_schema=False)
async def get_cart(
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await _get_cart_response(
        x_session_id=x_session_id,
        current_user=current_user,
        db=db,
    )


@router.post("/api/v1/cart/items", response_model=CartResponse)
@router.post("/cart/items", response_model=CartResponse, include_in_schema=False)
async def add_item(
    data: CartItemAdd,
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    await svc.add_item(cart.id, data)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.patch("/api/v1/cart/items/{item_id}", response_model=CartResponse)
@router.patch("/cart/items/{item_id}", response_model=CartResponse, include_in_schema=False)
async def update_item(
    item_id: UUID,
    data: CartItemUpdate,
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    await svc.update_item(item_id, data, cart_id=cart.id)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.delete("/api/v1/cart/items/{item_id}", response_model=CartResponse)
@router.delete("/cart/items/{item_id}", response_model=CartResponse, include_in_schema=False)
async def remove_item(
    item_id: UUID,
    x_session_id: str | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(user=current_user, session_id=x_session_id)
    await svc.remove_item(item_id, cart_id=cart.id)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)
