from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db, get_optional_user
from src.models.user import User
from src.schemas.cart import (
    CartItemAdd,
    CartItemUpdate,
    CartResponse,
    CartValidateResponse,
)
from src.services.cart_service import CartService

router = APIRouter(tags=["cart"])


async def _get_cart_response(
    *,
    x_session_id: UUID | None,
    current_user: User | None,
    db: AsyncSession,
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.get("/api/v1/cart", response_model=CartResponse)
@router.get("/cart", response_model=CartResponse, include_in_schema=False)
async def get_cart(
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await _get_cart_response(
        x_session_id=x_session_id,
        current_user=current_user,
        db=db,
    )


@router.post(
    "/api/v1/cart/validate",
    response_model=CartValidateResponse,
    response_model_exclude_none=True,
)
async def validate_cart(
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await db.commit()
    return await svc.validate_cart(cart.id)


@router.post("/api/v1/cart/merge", response_model=CartResponse)
@router.post("/cart/merge", response_model=CartResponse, include_in_schema=False)
async def merge_guest_cart(
    x_session_id: UUID = Header(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.merge_guest_cart(current_user, str(x_session_id))
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.post(
    "/api/v1/cart/items",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
)
@router.post("/cart/items", response_model=CartResponse, include_in_schema=False)
async def add_item(
    data: CartItemAdd,
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await svc.add_item(cart.id, data)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.patch("/api/v1/cart/items/{sku_id}", response_model=CartResponse)
@router.patch("/cart/items/{sku_id}", response_model=CartResponse, include_in_schema=False)
async def patch_item_by_sku(
    sku_id: UUID,
    data: CartItemUpdate,
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await svc.update_item(sku_id, data, cart_id=cart.id)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.delete("/api/v1/cart/items/{sku_id}", response_model=CartResponse)
@router.delete("/cart/items/{sku_id}", response_model=CartResponse, include_in_schema=False)
async def remove_item(
    sku_id: UUID,
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await svc.remove_item(sku_id, cart_id=cart.id)
    await db.commit()
    return await svc.get_enriched_cart(cart.id)


@router.delete("/api/v1/cart", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/cart", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def clear_cart(
    x_session_id: UUID | None = Header(default=None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    svc = CartService(db)
    cart = await svc.get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    await svc.clear_cart(cart.id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
