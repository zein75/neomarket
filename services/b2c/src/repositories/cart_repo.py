from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.cart import Cart, CartItem

from .base import BaseRepository


class CartRepository(BaseRepository[Cart]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Cart)

    async def get_by_user_id(self, user_id: UUID) -> Cart | None:
        result = await self.session.execute(
            select(Cart)
            .where(Cart.user_id == user_id)
            .options(selectinload(Cart.items))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(self, session_id: str) -> Cart | None:
        result = await self.session.execute(
            select(Cart)
            .where(Cart.session_id == session_id)
            .options(selectinload(Cart.items))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_with_items(self, cart_id: UUID) -> Cart | None:
        result = await self.session.execute(
            select(Cart)
            .where(Cart.id == cart_id)
            .options(selectinload(Cart.items))
        )
        return result.scalar_one_or_none()

    async def get_item(self, item_id: UUID) -> CartItem | None:
        return await self.session.get(CartItem, item_id)

    async def add_item(
        self,
        cart_id: UUID,
        sku_id: UUID,
        product_id: UUID,
        quantity: int,
        unit_price: int,
    ) -> CartItem:
        item = CartItem(
            cart_id=cart_id,
            sku_id=sku_id,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update_item_quantity(self, item: CartItem, quantity: int) -> CartItem:
        item.quantity = quantity
        await self.session.flush()
        return item

    async def remove_item(self, item: CartItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    async def remove_cart(self, cart: Cart) -> None:
        await self.session.delete(cart)
        await self.session.flush()
