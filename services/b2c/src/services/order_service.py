from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order, OrderItem
from src.repositories.cart_repo import CartRepository
from src.repositories.order_repo import OrderRepository


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.order_repo = OrderRepository(session)
        self.cart_repo = CartRepository(session)

    async def create_from_cart(self, user_id: UUID, cart_id: UUID) -> Order:
        cart = await self.cart_repo.get_with_items(cart_id)
        if not cart or not cart.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cart is empty",
            )

        total = sum(item.quantity * item.unit_price for item in cart.items)
        order = await self.order_repo.create(
            user_id=user_id,
            total_amount=total,
            currency=cart.currency,
        )

        for cart_item in cart.items:
            order_item = OrderItem(
                order_id=order.id,
                sku_id=cart_item.sku_id,
                product_id=cart_item.product_id,
                # Snapshots — populated from B2B data in a real integration
                product_title="",
                sku_name="",
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
                line_total=cart_item.quantity * cart_item.unit_price,
            )
            self.order_repo.session.add(order_item)

        # Clear cart
        for cart_item in list(cart.items):
            await self.cart_repo.remove_item(cart_item)

        await self.order_repo.session.flush()
        return await self.order_repo.get_with_items(order.id)

    async def list_orders(self, user_id: UUID) -> list[Order]:
        return await self.order_repo.list_by_user(user_id)

    async def get_order(self, order_id: UUID, user_id: UUID) -> Order:
        order = await self.order_repo.get_with_items(order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
            )
        if order.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        return order
