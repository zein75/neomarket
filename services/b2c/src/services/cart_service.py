from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cart import Cart, CartItem
from src.models.user import User
from src.repositories.cart_repo import CartRepository
from src.schemas.cart import CartItemAdd, CartItemUpdate


class CartService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CartRepository(session)

    async def get_or_create_cart(
        self,
        user: User | None = None,
        session_id: str | None = None,
    ) -> Cart:
        if user:
            cart = await self.repo.get_by_user_id(user.id)
            if not cart:
                cart = await self.repo.create(user_id=user.id)
        elif session_id:
            cart = await self.repo.get_by_session_id(session_id)
            if not cart:
                cart = await self.repo.create(session_id=session_id)
        else:
            cart = await self.repo.create()
        return cart

    async def get_cart_with_items(self, cart_id: UUID) -> Cart:
        cart = await self.repo.get_with_items(cart_id)
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found"
            )
        return cart

    async def add_item(self, cart_id: UUID, data: CartItemAdd) -> CartItem:
        cart = await self.repo.get_with_items(cart_id)
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found"
            )
        # If SKU already in cart — accumulate quantity
        for item in cart.items:
            if item.sku_id == data.sku_id:
                return await self.repo.update_item_quantity(
                    item, item.quantity + data.quantity
                )
        return await self.repo.add_item(
            cart_id=cart_id,
            sku_id=data.sku_id,
            product_id=data.product_id,
            quantity=data.quantity,
            unit_price=data.unit_price,
        )

    async def update_item(self, item_id: UUID, data: CartItemUpdate) -> CartItem:
        item = await self.repo.get_item(item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        if data.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quantity must be greater than 0",
            )
        return await self.repo.update_item_quantity(item, data.quantity)

    async def remove_item(self, item_id: UUID) -> None:
        item = await self.repo.get_item(item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        await self.repo.remove_item(item)
