import logging
from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.order import Order, OrderItem, OrderStatus
from src.repositories.cart_repo import CartRepository
from src.repositories.order_repo import OrderRepository
from src.schemas.order import OrderCreateRequest, OrderPaginatedResponse


logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.order_repo = OrderRepository(session)
        self.cart_repo = CartRepository(session)

    async def checkout(
        self,
        user_id: UUID,
        cart_id: UUID,
        idempotency_key: str,
        order_request: OrderCreateRequest | None = None,
    ) -> Order:
        existing = await self.order_repo.get_by_idempotency_key(idempotency_key)
        if existing:
            return existing

        cart = await self.cart_repo.get_with_items(cart_id)
        if not cart or not cart.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cart is empty",
            )

        snapshots = await self._build_item_snapshots(cart.items)
        self._validate_snapshots(cart.items, snapshots)
        order_id = uuid4()
        await self._reserve(order_id, idempotency_key, cart.items)

        total = sum(
            item.quantity * int(snapshots[str(item.sku_id)]["price"])
            for item in cart.items
        )
        order = await self.order_repo.create(
            id=order_id,
            user_id=user_id,
            status=OrderStatus.PAID,
            total_amount=total,
            currency=cart.currency,
            address_id=order_request.address_id if order_request else None,
            payment_method_id=(
                order_request.payment_method_id if order_request else None
            ),
            address=self._address_snapshot(order_request),
            idempotency_key=idempotency_key,
        )

        for cart_item in cart.items:
            snapshot = snapshots[str(cart_item.sku_id)]
            order_item = OrderItem(
                order_id=order.id,
                sku_id=cart_item.sku_id,
                product_id=cart_item.product_id,
                product_title=str(snapshot["product_title"]),
                sku_name=str(snapshot["sku_name"]),
                quantity=cart_item.quantity,
                unit_price=int(snapshot["price"]),
                line_total=cart_item.quantity * int(snapshot["price"]),
            )
            self.order_repo.session.add(order_item)
            order.items.append(order_item)

        for cart_item in list(cart.items):
            await self.cart_repo.remove_item(cart_item)

        await self.order_repo.session.flush()
        return await self.order_repo.get_with_items(order.id) or order

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
            idempotency_key=f"legacy-{uuid4()}",
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

    async def list_orders(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
        status_filter: OrderStatus | None = None,
    ) -> OrderPaginatedResponse:
        orders, total_count = await self.order_repo.list_for_user(
            user_id,
            limit=limit,
            offset=offset,
            status_filter=status_filter,
        )
        return OrderPaginatedResponse(
            items=orders,
            total_count=total_count,
            limit=limit,
            offset=offset,
        )

    async def get_order(self, order_id: UUID, user_id: UUID) -> Order:
        order = await self.order_repo.get_user_order_with_items(order_id, user_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
            )
        return order

    async def cancel_order(self, order_id: UUID, user_id: UUID) -> Order:
        order = await self.order_repo.get_with_items(order_id)
        if not order or order.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
        cancellable_statuses = {
            OrderStatus.CREATED,
            OrderStatus.PAID,
            OrderStatus.ASSEMBLING,
            OrderStatus.DELIVERING,
        }
        if order.status not in cancellable_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "CANCEL_NOT_ALLOWED",
                    "message": "Order cannot be cancelled in current status",
                    "current_status": order.status.value,
                },
            )

        try:
            await self._unreserve(order)
        except HTTPException:
            logger.exception("Failed to unreserve cancelled order %s", order.id)
            order.status = OrderStatus.CANCEL_PENDING
            await self.order_repo.session.flush()
            return order

        order.status = OrderStatus.CANCELLED
        await self.order_repo.session.flush()
        return order

    async def mark_delivered(self, order_id: UUID) -> Order:
        order = await self.order_repo.get_with_items(order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
            )
        if order.status in {OrderStatus.CANCELLED, OrderStatus.CANCEL_PENDING}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DELIVERY_NOT_ALLOWED",
                    "message": "Cancelled order cannot be delivered",
                    "current_status": order.status.value,
                },
            )

        order.status = OrderStatus.DELIVERED
        await self.order_repo.session.flush()
        fulfilled = await self._try_fulfill(order)
        if not fulfilled:
            await self.order_repo.queue_fulfillment_retry(
                order,
                "B2B fulfill failed",
            )
        return order

    async def retry_pending_fulfillments(self, limit: int = 100) -> int:
        retried = 0
        pending_fulfillments = await self.order_repo.list_pending_fulfillments(
            limit=limit
        )
        for pending in pending_fulfillments:
            order = pending.order
            if order.status != OrderStatus.DELIVERED:
                await self.order_repo.delete_pending_fulfillment(pending)
                continue
            fulfilled = await self._try_fulfill(order)
            if fulfilled:
                await self.order_repo.delete_pending_fulfillment(pending)
                retried += 1
            else:
                await self.order_repo.queue_fulfillment_retry(
                    order,
                    "B2B fulfill retry failed",
                )
        return retried

    async def _build_item_snapshots(
        self,
        cart_items: list[object],
    ) -> dict[str, dict[str, object]]:
        product_ids = sorted({str(item.product_id) for item in cart_items})
        async with B2BClient(settings.b2b_base_url) as client:
            products = await client.get_products_batch(product_ids)

        snapshots: dict[str, dict[str, object]] = {}
        for product in products:
            for sku in product.get("skus", []):
                snapshots[str(sku.get("id"))] = {
                    "product_id": str(product.get("id")),
                    "product_title": product.get("title") or "",
                    "sku_name": sku.get("name") or "",
                    "price": int(sku.get("price", 0)),
                    "active_quantity": int(sku.get("active_quantity", 0)),
                }
        return snapshots

    def _validate_snapshots(
        self,
        cart_items: list[object],
        snapshots: dict[str, dict[str, object]],
    ) -> None:
        failed_items = []
        for item in cart_items:
            snapshot = snapshots.get(str(item.sku_id))
            if not snapshot:
                failed_items.append({"sku_id": str(item.sku_id), "reason": "SKU_NOT_FOUND"})
                continue
            if str(snapshot["product_id"]) != str(item.product_id):
                failed_items.append({"sku_id": str(item.sku_id), "reason": "SKU_NOT_FOUND"})
                continue
            if int(snapshot["active_quantity"]) < item.quantity:
                failed_items.append(
                    {"sku_id": str(item.sku_id), "reason": "INSUFFICIENT_STOCK"}
                )

        if failed_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RESERVE_FAILED",
                    "message": "Unable to reserve one or more items",
                    "failed_items": failed_items,
                },
            )

    async def _reserve(
        self,
        order_id: UUID,
        idempotency_key: str,
        cart_items: list[object],
    ) -> None:
        payload = {
            "order_id": str(order_id),
            "idempotency_key": idempotency_key,
            "items": [
                {"sku_id": str(item.sku_id), "quantity": item.quantity}
                for item in cart_items
            ],
        }
        async with B2BClient(settings.b2b_base_url) as client:
            try:
                await client.reserve(payload)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_409_CONFLICT:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=self._reserve_failure_detail(exc.detail),
                    )
                raise

    async def _unreserve(self, order: Order) -> None:
        async with B2BClient(settings.b2b_base_url) as client:
            await client.unreserve({"order_id": str(order.id)})

    async def _try_fulfill(self, order: Order) -> bool:
        payload = {
            "order_id": str(order.id),
            "items": [
                {"sku_id": str(item.sku_id), "quantity": item.quantity}
                for item in order.items
            ],
        }
        async with B2BClient(settings.b2b_base_url) as client:
            try:
                await client.fulfill(payload)
                return True
            except HTTPException:
                logger.exception("Failed to fulfill delivered order %s", order.id)
                return False

    def _reserve_failure_detail(self, detail: object) -> object:
        if isinstance(detail, dict) and "failed_items" in detail:
            return {
                "code": detail.get("code", "RESERVE_FAILED"),
                "message": detail.get(
                    "message",
                    "Unable to reserve one or more items",
                ),
                "failed_items": detail["failed_items"],
            }
        if isinstance(detail, dict) and "sku_ids" in detail:
            return {
                "code": "RESERVE_FAILED",
                "message": "Unable to reserve one or more items",
                "failed_items": [
                    {"sku_id": sku_id, "reason": "INSUFFICIENT_STOCK"}
                    for sku_id in detail["sku_ids"]
                ],
            }
        return {
            "code": "RESERVE_FAILED",
            "message": "Unable to reserve one or more items",
            "failed_items": [],
        }

    def _address_snapshot(
        self,
        order_request: OrderCreateRequest | None,
    ) -> dict[str, object]:
        if order_request is None:
            return {}
        return {"id": str(order_request.address_id)}
