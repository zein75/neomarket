import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
import inspect
from sqlalchemy import select
from uuid import UUID
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.order import (
    CheckoutAttemptStatus,
    CheckoutCompensationState,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    SellerOrderOutbox,
)
from src.repositories.cart_repo import CartRepository
from src.repositories.address_repo import AddressRepository
from src.repositories.order_repo import OrderRepository
from src.schemas.order import OrderCreateRequest, OrderPaginatedResponse


logger = logging.getLogger(__name__)
CANCEL_RETRY_BASE_SECONDS = 30
CANCEL_RETRY_MAX_SECONDS = 3600
# A checkout intent must survive a process crash after B2B accepts reserve.
# The grace period keeps the recovery worker from racing a healthy request
# between reserve and the local order commit.
CHECKOUT_INTENT_GRACE_SECONDS = 60


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.order_repo = OrderRepository(session)
        self.cart_repo = CartRepository(session)
        self.address_repo = AddressRepository(session)
        self.last_checkout_replayed = False

    async def checkout(
        self,
        user_id: UUID,
        cart_id: UUID | None,
        idempotency_key: str,
        order_request: OrderCreateRequest | None = None,
    ) -> Order:
        self.last_checkout_replayed = False
        request_fingerprint = self._request_fingerprint(order_request)
        # The lock must be acquired before the idempotency lookup and before
        # inventory reservation. Otherwise a concurrent request can reserve
        # the same cart and fail before it observes the winning order.
        lock_key = getattr(self.order_repo, "lock_idempotency_key", None)
        if lock_key is not None:
            await lock_key(idempotency_key)
        existing = await self.order_repo.get_by_idempotency_key(idempotency_key)
        if existing:
            if existing.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
                )
            return self._return_idempotent_order(existing, request_fingerprint)

        cart = await self.cart_repo.get_with_items(cart_id) if cart_id else None
        if not cart or not cart.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Cart is empty"},
            )

        address = await self.address_repo.get_for_user(order_request.address_id, user_id)
        if address is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ADDRESS_NOT_FOUND", "message": "Address not found"},
            )
        items = list(cart.items)
        # A failed order flush rolls the session back and expires ORM instances.
        # Keep the exact B2B payload as plain data before any transactional work
        # so durable compensation never tries an async lazy refresh afterwards.
        reservation_items = self._reservation_items(items)

        snapshots = await self._build_item_snapshots(items)
        self._validate_snapshots(items, snapshots)
        self._validate_item_snapshot(order_request, items, snapshots)
        # A deterministic operation id lets concurrent retries use the same
        # B2B reservation.  The durable row is committed before B2B is called:
        # after a crash the worker can compensate an orphaned reservation.
        order_id = self._checkout_operation_id(user_id, idempotency_key)
        try:
            await self._prepare_checkout_intent(
                order_id=order_id,
                buyer_id=user_id,
                items=reservation_items,
                request_fingerprint=request_fingerprint,
            )
            await self._create_checkout_attempt(
                attempt_id=order_id,
                buyer_id=user_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            await self.order_repo.session.commit()
        except IntegrityError:
            # Another same-buyer/same-key request created the intent first.
            await self.order_repo.session.rollback()
            pending = await self.order_repo.get_reservation_compensation(order_id)
            if pending is None:
                raise
            self._validate_checkout_intent(pending, request_fingerprint)

        # The intent commit ends the idempotency-key transaction.  From this
        # point checkout and the orphan-compensation worker must share the
        # *operation* lock (the deterministic order id), otherwise the worker
        # can observe no Order, then unreserve after a retry commits one.
        operation_lock = getattr(self.order_repo, "lock_checkout_operation", None)
        if operation_lock is not None:
            await operation_lock(order_id)
        pending_for_update = getattr(
            self.order_repo, "get_reservation_compensation_for_update", None
        )
        pending = (
            await pending_for_update(order_id)
            if pending_for_update is not None
            else await self.order_repo.get_reservation_compensation(order_id)
        )
        existing = await self.order_repo.get_by_idempotency_key(idempotency_key)
        if existing:
            if existing.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
                )
            await self._delete_checkout_intent(order_id)
            return self._return_idempotent_order(existing, request_fingerprint)
        if pending is not None:
            self._validate_checkout_intent(pending, request_fingerprint)
            self._raise_if_checkout_operation_compensating(pending)

        try:
            await self._reserve(order_id, idempotency_key, items)
        except HTTPException as exc:
            # A B2B 409 is an all-or-nothing business rejection, so no stock
            # was reserved and the intent can be completed.  A 503 can mean
            # that B2B reserved stock but its response was lost: retain the
            # intent for idempotent replay or worker compensation.
            if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
                await self._delete_checkout_intent(order_id, best_effort=True)
                await self._set_checkout_attempt_status(
                    order_id, status=CheckoutAttemptStatus.FAILED, error_code="RESERVATION_REJECTED"
                )
            else:
                # The intent was committed before the operation lock.  Release
                # this request transaction/lock while retaining that durable
                # record for a same-key retry or the recovery worker.
                await self.order_repo.session.rollback()
                await self._set_checkout_attempt_status(
                    order_id, status=CheckoutAttemptStatus.PENDING, error_code="CHECKOUT_UNAVAILABLE"
                )
            raise
        except Exception:
            # Transport exceptions have the same ambiguous outcome as a lost
            # response.  Never delete the only durable recovery record here.
            await self.order_repo.session.rollback()
            raise

        total = sum(
            item.quantity * int(snapshots[str(item.sku_id)]["price"])
            for item in items
        )
        try:
            try:
                order = await self.order_repo.create(
                    id=order_id,
                    user_id=user_id,
                    # Checkout only reserves inventory and persists the order.
                    # Payment is confirmed separately by a verified PSP
                    # webhook; never report PAID from a local checkout call.
                    status=OrderStatus.CREATED,
                    total_amount=total,
                    currency=cart.currency,
                    address_id=order_request.address_id if order_request else None,
                    delivery_method=(
                        order_request.delivery_method if order_request else None
                    ),
                    payment_method_id=(
                        order_request.payment_method_id if order_request else None
                    ),
                    contact=(
                        order_request.contact.model_dump(mode="json")
                        if order_request and order_request.contact
                        else None
                    ),
                    legal_consents=(
                        [consent.model_dump(mode="json") for consent in order_request.legal_consents]
                        if order_request and order_request.legal_consents
                        else None
                    ),
                    quote_id=order_request.quote_id if order_request else None,
                    address=self._address_snapshot(order_request, address),
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
            except IntegrityError:
                # A concurrent request may have won the unique idempotency-key
                # insert. Its result is the result for both requests.
                await self.order_repo.session.rollback()
                existing = await self.order_repo.get_by_idempotency_key(idempotency_key)
                if existing is None:
                    raise
                if existing.user_id != user_id:
                    # Different buyers can race on the globally unique header
                    # key. Their operation ids differ, so only the losing
                    # reservation is compensated.
                    await self._compensate_checkout_reservation(
                        order_id,
                        user_id,
                        reservation_items,
                        "idempotency key belongs to another buyer",
                    )
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
                    )
                await self._delete_checkout_intent(order_id)
                return self._return_idempotent_order(existing, request_fingerprint)

            for cart_item in items:
                snapshot = snapshots[str(cart_item.sku_id)]
                order_item = OrderItem(
                    order_id=order.id,
                    sku_id=cart_item.sku_id,
                    product_id=cart_item.product_id,
                    seller_id=UUID(str(snapshot["seller_id"])),
                    product_title=str(snapshot["product_title"]),
                    sku_name=str(snapshot["sku_name"]),
                    quantity=cart_item.quantity,
                    unit_price=int(snapshot["price"]),
                    line_total=cart_item.quantity * int(snapshot["price"]),
                )
                self.order_repo.session.add(order_item)
                order.__dict__.setdefault("items", []).append(order_item)

            await self.order_repo.session.flush()
            await self._queue_seller_order_allocations(order)
            await self._set_checkout_attempt_status(
                order_id, status=CheckoutAttemptStatus.COMPLETED, order_id=order.id
            )
            # The order is the durable confirmation of the saga.  It must be
            # committed here, not in the HTTP router after this method returns.
            await self.order_repo.session.commit()
            await self._delete_checkout_intent(order_id)
            # Response serialization includes status_history.  Return only the
            # explicitly eager-loaded aggregate; falling back to ``order`` can
            # trigger an async lazy load while FastAPI serializes the response.
            return await self._load_order_for_response(order.id)
        except Exception as checkout_error:
            # A failed flush/commit leaves a real SQLAlchemy transaction
            # unusable. The already committed intent remains available to the
            # recovery worker even if direct compensation also fails.
            await self.order_repo.session.rollback()
            await self._compensate_checkout_reservation(
                order_id,
                user_id,
                reservation_items,
                f"{type(checkout_error).__name__}: {checkout_error}",
            )
            await self._set_checkout_attempt_status(
                order_id, status=CheckoutAttemptStatus.FAILED, error_code="CHECKOUT_FAILED"
            )
            raise

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
                product_title="",
                sku_name="",
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
                line_total=cart_item.quantity * cart_item.unit_price,
            )
            self.order_repo.session.add(order_item)

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

    async def cancel_order(
        self,
        order_id: UUID,
        user_id: UUID,
        reason: str | None = None,
    ) -> Order:
        order = await self.order_repo.get_with_items_for_update(order_id)
        if not order or order.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
            )
        # Cancellation is a durable state transition. A client retry after a
        # lost response must observe the accepted result instead of issuing a
        # second unreserve or receiving a misleading conflict.
        if order.status in {OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED}:
            return order
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

        order.cancel_reason = reason
        order.cancelled_at = datetime.now(timezone.utc)
        # Record the accepted cancellation intent before contacting B2B. The
        # request transaction persists it even when unreserve fails, so retry
        # can safely continue after a restart.
        order.status = OrderStatus.CANCEL_PENDING
        await self._queue_seller_order_cancellations(order)
        order.status_history.append(
            OrderStatusHistory(
                order_id=order.id,
                status=OrderStatus.CANCEL_PENDING,
                changed_at=datetime.now(timezone.utc),
                reason=reason,
            )
        )
        await self.order_repo.session.flush()
        # Commit intent before B2B. A successful unreserve must never be
        # followed by a rollback to PAID when the router later commits.
        await self.order_repo.session.commit()

        try:
            await self._unreserve(order)
        except Exception:  # noqa: BLE001 - cancellation must remain accepted for async retry
            logger.exception("Failed to unreserve cancelled order %s", order.id)
            self._schedule_cancel_retry(order)
            self._sync_order_address(order)
            await self.order_repo.session.flush()
            # CANCEL_PENDING was already committed; persist retry metadata
            # independently and leave the durable state pending if this commit
            # happens to fail.
            try:
                await self.order_repo.session.commit()
            except Exception:  # noqa: BLE001 - pending intent is durable
                await self.order_repo.session.rollback()
            return await self._load_order_for_response(order.id)

        order.status = OrderStatus.CANCELLED
        order.cancel_retry_at = None
        order.status_history.append(
            OrderStatusHistory(
                order_id=order.id,
                status=OrderStatus.CANCELLED,
                changed_at=datetime.now(timezone.utc),
                reason=reason,
            )
        )
        self._sync_order_address(order)
        await self.order_repo.session.flush()
        try:
            await self.order_repo.session.commit()
        except Exception:  # noqa: BLE001 - committed CANCEL_PENDING is retried
            await self.order_repo.session.rollback()
        return await self._load_order_for_response(order.id)

    async def mark_delivered(self, order_id: UUID) -> Order:
        order = await self.order_repo.get_with_items_for_update(order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
            )
        if order.status not in {OrderStatus.DELIVERING, OrderStatus.DELIVERED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DELIVERY_NOT_ALLOWED",
                    "message": "Order cannot be delivered in current status",
                    "current_status": order.status.value,
                },
            )

        order.status = OrderStatus.DELIVERED
        await self.order_repo.session.flush()
        fulfilled = await self._try_fulfill(order)
        if not fulfilled:
            await self._queue_fulfillment_retry(order, "B2B fulfill failed", 1)
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
                await self._queue_fulfillment_retry(
                    order, "B2B fulfill retry failed", pending.attempts + 1
                )
        return retried

    async def retry_pending_cancellations(self, limit: int = 100) -> int:
        retried = 0
        # Cancellation retries commit each successful row to make progress
        # durable. Select one row per transaction so that a worker never holds
        # locks for a batch it will later commit item-by-item.
        limit = min(limit, 1)
        orders = await self.order_repo.list_due_cancellation_retries(
            datetime.now(timezone.utc), limit
        )
        for order in orders:
            try:
                await self._unreserve(order)
            except Exception:  # noqa: BLE001 - keep retrying other pending cancellations
                logger.exception("Failed to retry cancellation for order %s", order.id)
                self._schedule_cancel_retry(order)
                await self.order_repo.session.flush()
                continue
            order.status = OrderStatus.CANCELLED
            order.cancel_retry_at = None
            order.status_history.append(
                OrderStatusHistory(
                    order_id=order.id,
                    status=OrderStatus.CANCELLED,
                    changed_at=datetime.now(timezone.utc),
                    reason=order.cancel_reason,
                )
            )
            await self.order_repo.session.flush()
            try:
                await self.order_repo.session.commit()
            except Exception:  # noqa: BLE001 - pending state remains durable
                await self.order_repo.session.rollback()
                continue
            retried += 1
        return retried

    async def retry_pending_reservation_compensations(self, limit: int = 100) -> int:
        """Retry unreserve jobs created when checkout failed after reserve."""
        retried = 0
        pending_jobs = await self.order_repo.list_due_reservation_compensations(
            datetime.now(timezone.utc), limit
        )
        for pending in pending_jobs:
            if await self._process_reservation_compensation(pending.order_id):
                retried += 1
        return retried

    @staticmethod
    def _schedule_cancel_retry(order: Order) -> None:
        order.cancel_retry_attempts = (order.cancel_retry_attempts or 0) + 1
        delay = min(
            CANCEL_RETRY_BASE_SECONDS * (2 ** (order.cancel_retry_attempts - 1)),
            CANCEL_RETRY_MAX_SECONDS,
        )
        order.cancel_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

    @staticmethod
    def _fulfillment_retry_at(attempt: int) -> datetime:
        delay = min(
            CANCEL_RETRY_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
            CANCEL_RETRY_MAX_SECONDS,
        )
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    async def _queue_fulfillment_retry(
        self, order: Order, error: str, attempt: int
    ) -> None:
        queue = self.order_repo.queue_fulfillment_retry
        if "next_retry_at" in inspect.signature(queue).parameters:
            await queue(order, error, next_retry_at=self._fulfillment_retry_at(attempt))
        else:
            await queue(order, error)

    async def _build_item_snapshots(
        self,
        cart_items: list[object],
    ) -> dict[str, dict[str, object]]:
        product_ids = sorted({str(item.product_id) for item in cart_items})
        async with B2BClient(settings.b2b_base_url) as client:
            try:
                products = await client.get_products_batch(product_ids)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    raise self._b2b_unavailable() from exc
                raise

        snapshots: dict[str, dict[str, object]] = {}
        for product in products:
            for sku in product.get("skus", []):
                snapshots[str(sku.get("id"))] = {
                    "product_id": str(product.get("id")),
                    "seller_id": str(product.get("seller_id") or ""),
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
            try:
                UUID(str(snapshot.get("seller_id") or ""))
            except ValueError:
                raise self._b2b_unavailable() from None
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

    def _validate_item_snapshot(
        self,
        order_request: OrderCreateRequest | None,
        items: list[object],
        snapshots: dict[str, dict[str, object]],
    ) -> None:
        if not order_request or order_request.items_snapshot is None:
            return
        expected = {
            str(item.sku_id): (item.quantity, int(snapshots[str(item.sku_id)]["price"]))
            for item in items
        }
        actual = {
            str(item.sku_id): (item.quantity, item.unit_price)
            for item in order_request.items_snapshot
        }
        if actual != expected:
            issues = []
            for sku_id, (quantity, price) in expected.items():
                requested = actual.get(sku_id)
                if requested is None:
                    issues.append(
                        {
                            "sku_id": sku_id,
                            "type": "QUANTITY_REDUCED",
                            "message": "Cart item is missing from the checkout snapshot",
                            "old_value": quantity,
                            "new_value": 0,
                        }
                    )
                    continue
                if requested[0] != quantity:
                    issues.append(
                        {
                            "sku_id": sku_id,
                            "type": "QUANTITY_REDUCED",
                            "message": "Cart item quantity has changed",
                            "old_value": requested[0],
                            "new_value": quantity,
                        }
                    )
                if requested[1] != price:
                    issues.append(
                        {
                            "sku_id": sku_id,
                            "type": "PRICE_CHANGED",
                            "message": "Cart item price has changed",
                            "old_value": requested[1],
                            "new_value": price,
                        }
                    )
            for sku_id in actual.keys() - expected.keys():
                issues.append(
                    {
                        "sku_id": sku_id,
                        "type": "QUANTITY_REDUCED",
                        "message": "Checkout snapshot contains an item absent from the cart",
                        "old_value": actual[sku_id][0],
                        "new_value": 0,
                    }
                )
            cart_items = []
            subtotal = 0
            for item in items:
                snapshot = snapshots[str(item.sku_id)]
                unit_price = int(snapshot["price"])
                line_total = item.quantity * unit_price
                subtotal += line_total
                cart_items.append(
                    {
                        "sku_id": str(item.sku_id),
                        "product_id": str(item.product_id),
                        "name": f'{snapshot["product_title"]} {snapshot["sku_name"]}'.strip(),
                        "quantity": item.quantity,
                        "unit_price": unit_price,
                        "unit_price_at_add": item.unit_price,
                        "line_total": line_total,
                        "available_quantity": int(snapshot["active_quantity"]),
                        "is_available": int(snapshot["active_quantity"]) >= item.quantity,
                        "unavailable_reason": None,
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "is_valid": False,
                    "cart": {
                        "id": str(items[0].cart_id),
                        "items": cart_items,
                        "items_count": sum(item.quantity for item in items),
                        "subtotal": subtotal,
                        "is_valid": False,
                    },
                    "issues": issues,
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
                reserve_response = await client.reserve(payload)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_409_CONFLICT:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=self._reserve_failure_detail(exc.detail),
                    )
                if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    raise self._b2b_unavailable() from exc
                raise
        if isinstance(reserve_response, dict) and reserve_response.get("reserved") is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=self._reserve_failure_detail(reserve_response),
            )

    async def _unreserve(self, order: Order) -> None:
        await self._unreserve_items(order.id, order.items)

    async def _unreserve_items(self, order_id: UUID, items: list[object]) -> None:
        payload_items = [
            {"sku_id": str(item.sku_id), "quantity": item.quantity}
            for item in items
        ]
        await self._unreserve_payload(order_id, payload_items)

    async def _unreserve_payload(
        self,
        order_id: UUID,
        items: list[dict[str, object]],
    ) -> None:
        payload = {"order_id": str(order_id), "items": items}
        async with B2BClient(settings.b2b_base_url) as client:
            await client.unreserve(payload)

    async def _queue_reservation_compensation(
        self,
        *,
        order_id: UUID,
        buyer_id: UUID | None = None,
        items: list[object],
        error: str,
    ) -> None:
        kwargs = {
            "order_id": order_id,
            "items": self._reservation_items(items),
            "error": error,
            "next_retry_at": self._next_retry_at(1),
        }
        if buyer_id is not None and "buyer_id" in inspect.signature(
            self.order_repo.queue_reservation_compensation
        ).parameters:
            kwargs["buyer_id"] = buyer_id
        await self.order_repo.queue_reservation_compensation(**kwargs)

    async def _prepare_checkout_intent(
        self,
        *,
        order_id: UUID,
        buyer_id: UUID,
        items: list[object],
        request_fingerprint: str,
    ) -> None:
        pending = await self.order_repo.get_reservation_compensation(order_id)
        if pending is not None:
            self._validate_checkout_intent(pending, request_fingerprint)
            self._raise_if_checkout_operation_compensating(pending)
            return
        kwargs = {
            "order_id": order_id,
            "items": self._reservation_items(items),
            "error": "checkout reserve intent",
            "next_retry_at": datetime.now(timezone.utc)
            + timedelta(seconds=CHECKOUT_INTENT_GRACE_SECONDS),
            "request_fingerprint": request_fingerprint,
        }
        if "buyer_id" in inspect.signature(
            self.order_repo.queue_reservation_compensation
        ).parameters:
            kwargs["buyer_id"] = buyer_id
        await self.order_repo.queue_reservation_compensation(**kwargs)

    async def _create_checkout_attempt(
        self,
        *,
        attempt_id: UUID,
        buyer_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> None:
        creator = getattr(self.order_repo, "create_checkout_attempt", None)
        if creator is None:
            return
        try:
            await creator(
                attempt_id=attempt_id,
                buyer_id=buyer_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHECKOUT_ATTEMPT_CONFLICT", "message": str(exc)},
            ) from exc

    async def _queue_seller_order_allocations(self, order: Order) -> None:
        """Persist one PII-free seller allocation event per owner in the order txn."""
        grouped: dict[UUID, list[OrderItem]] = {}
        for item in order.items:
            if item.seller_id is None:
                raise self._b2b_unavailable()
            grouped.setdefault(item.seller_id, []).append(item)

        for seller_id, items in grouped.items():
            seller_order_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order:{order.id}:{seller_id}")
            event_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order-allocation:{order.id}:{seller_id}:v1")
            lines = [
                {
                    "sku_id": str(item.sku_id),
                    "product_id": str(item.product_id),
                    "product_title": item.product_title,
                    "sku_name": item.sku_name,
                    "quantity": item.quantity,
                    "unit_price_minor": item.unit_price,
                    "line_total_minor": item.line_total,
                }
                for item in items
            ]
            payload = {
                "schema_version": 1,
                "event_id": str(event_id),
                "event_type": "seller_order.allocated.v1",
                "producer": "b2c",
                "aggregate_type": "seller_order",
                "aggregate_id": str(seller_order_id),
                "aggregate_version": 1,
                "tenant_id": str(seller_id),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "correlation_id": str(order.id),
                "payload": {
                    "buyer_order_id": str(order.id),
                    "seller_order_id": str(seller_order_id),
                    "seller_id": str(seller_id),
                    "currency": order.currency,
                    "status": "CREATED",
                    "total_minor": sum(line["line_total_minor"] for line in lines),
                    "items": lines,
                },
            }
            payload["payload_hash"] = hashlib.sha256(
                json.dumps(
                    payload["payload"], sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self.order_repo.session.add(
                SellerOrderOutbox(
                    event_id=event_id,
                    seller_order_id=seller_order_id,
                    payload=payload,
                    payload_sha256=digest,
                )
            )

    async def _queue_seller_order_cancellations(self, order: Order) -> None:
        """Persist PII-free seller cancellation events with the buyer intent."""
        seller_ids = {item.seller_id for item in order.items if item.seller_id is not None}
        for seller_id in seller_ids:
            seller_order_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order:{order.id}:{seller_id}")
            event_id = uuid5(
                NAMESPACE_URL, f"neomarket:seller-order-cancellation:{order.id}:{seller_id}:v1"
            )
            payload = {
                "schema_version": 1,
                "event_id": str(event_id),
                "event_type": "seller_order.cancelled.v1",
                "producer": "b2c",
                "aggregate_type": "seller_order",
                "aggregate_id": str(seller_order_id),
                "aggregate_version": 2,
                "tenant_id": str(seller_id),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "correlation_id": str(order.id),
                "payload": {
                    "buyer_order_id": str(order.id),
                    "seller_order_id": str(seller_order_id),
                    "seller_id": str(seller_id),
                },
            }
            payload["payload_hash"] = hashlib.sha256(
                json.dumps(payload["payload"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self.order_repo.session.add(
                SellerOrderOutbox(
                    event_id=event_id,
                    seller_order_id=seller_order_id,
                    payload=payload,
                    payload_sha256=digest,
                )
            )

    async def retry_pending_seller_order_events(self, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        result = await self.order_repo.session.execute(
            select(SellerOrderOutbox)
            .where(
                SellerOrderOutbox.status.in_(["PENDING", "RETRY"]),
                (SellerOrderOutbox.next_retry_at.is_(None) | (SellerOrderOutbox.next_retry_at <= now)),
                (SellerOrderOutbox.lease_until.is_(None) | (SellerOrderOutbox.lease_until < now)),
            )
            .order_by(SellerOrderOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(result.scalars().all())
        delivered = 0
        for event in events:
            event.lease_until = now + timedelta(seconds=30)
            event.attempts += 1
            actual_hash = hashlib.sha256(
                json.dumps(event.payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if actual_hash != event.payload_sha256:
                event.status = "DEAD"
                event.last_error = "OUTBOX_PAYLOAD_HASH_MISMATCH"
                event.lease_until = None
                continue
            try:
                async with B2BClient(settings.b2b_base_url) as client:
                    if event.payload.get("event_type") == "seller_order.cancelled.v1":
                        await client.send_seller_order_cancellation(event.payload)
                    else:
                        await client.send_seller_order_allocation(event.payload)
                event.status = "SENT"
                event.last_error = None
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - retry after transient upstream failure
                event.status = "RETRY"
                event.last_error = str(exc)[:500]
                event.next_retry_at = now + timedelta(seconds=min(900, 2 ** min(event.attempts, 10)))
            finally:
                event.lease_until = None
        await self.order_repo.session.flush()
        return delivered

    async def _set_checkout_attempt_status(
        self,
        attempt_id: UUID,
        *,
        status: CheckoutAttemptStatus,
        order_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        updater = getattr(self.order_repo, "set_checkout_attempt_status", None)
        if updater is None:
            return
        try:
            await updater(
                attempt_id,
                status=status,
                order_id=order_id,
                error_code=error_code,
            )
            await self.order_repo.session.commit()
        except Exception:  # noqa: BLE001 - status projection must not hide saga result
            await self.order_repo.session.rollback()
            logger.exception("Could not update checkout attempt %s", attempt_id)

    async def _delete_checkout_intent(
        self, order_id: UUID, *, best_effort: bool = False
    ) -> None:
        try:
            pending = await self.order_repo.get_reservation_compensation(order_id)
            if pending is None:
                return
            await self.order_repo.delete_reservation_compensation(pending)
            await self.order_repo.session.commit()
        except Exception:  # noqa: BLE001 - the durable worker resolves stale intent
            await self.order_repo.session.rollback()
            if not best_effort:
                logger.exception("Could not remove checkout intent %s", order_id)

    async def _compensate_checkout_reservation(
        self,
        order_id: UUID,
        buyer_id: UUID | None,
        items: list[object],
        error: str,
    ) -> None:
        # The intent was committed before reserve.  Make any direct
        # compensation use the same durable PENDING -> COMPENSATING ->
        # COMPENSATED state machine as the restart worker; otherwise a crash
        # after B2B success could resurrect an unreserved order on retry.
        await self._queue_reservation_compensation(
            order_id=order_id,
            buyer_id=buyer_id,
            items=items,
            error=error,
        )
        try:
            await self.order_repo.session.commit()
        except Exception:  # noqa: BLE001 - original intent remains durable
            await self.order_repo.session.rollback()
            return
        await self._process_reservation_compensation(order_id)

    @staticmethod
    def _reservation_items(items: list[object]) -> list[dict[str, object]]:
        """Materialize a B2B reservation payload without retaining ORM state."""
        return [
            {
                "sku_id": str(item["sku_id"])
                if isinstance(item, dict)
                else str(item.sku_id),
                "quantity": int(item["quantity"])
                if isinstance(item, dict)
                else int(item.quantity),
            }
            for item in items
        ]

    async def _process_reservation_compensation(self, order_id: UUID) -> bool:
        """Run one durable, restart-safe unreserve attempt for an operation.

        The first commit records ``COMPENSATING`` *before* B2B is contacted.
        Thus a crash after an otherwise successful unreserve leaves a durable
        poison-pill for checkout retries; a later worker can safely replay the
        idempotent unreserve and record the final tombstone.
        """
        operation_lock = getattr(self.order_repo, "lock_checkout_operation", None)
        if operation_lock is not None:
            await operation_lock(order_id)
        pending_for_update = getattr(
            self.order_repo, "get_reservation_compensation_for_update", None
        )

        async def current_intent():
            return (
                await pending_for_update(order_id)
                if pending_for_update is not None
                else await self.order_repo.get_reservation_compensation(order_id)
            )

        pending = await current_intent()
        if pending is None or self._is_compensation_complete(pending):
            return False
        # A committed order always wins: this is a stale recovery intent and
        # must never remove the real reservation behind that order.
        if await self.order_repo.get_with_items(order_id):
            await self.order_repo.delete_reservation_compensation(pending)
            try:
                await self.order_repo.session.commit()
            except Exception:  # noqa: BLE001 - harmless stale intent retry
                await self.order_repo.session.rollback()
                return False
            return True

        if self._compensation_state(pending) is CheckoutCompensationState.PENDING:
            await self.order_repo.mark_reservation_compensating(pending)
            try:
                # This commit is deliberately before the external call.
                await self.order_repo.session.commit()
            except Exception:  # noqa: BLE001 - leave PENDING for recovery
                await self.order_repo.session.rollback()
                return False

            # Commit releases PostgreSQL's transaction-scoped advisory lock;
            # reacquire it and reload the row before the network side effect.
            if operation_lock is not None:
                await operation_lock(order_id)
            pending = await current_intent()
            if pending is None or self._is_compensation_complete(pending):
                return False
            if await self.order_repo.get_with_items(order_id):
                await self.order_repo.delete_reservation_compensation(pending)
                try:
                    await self.order_repo.session.commit()
                except Exception:  # noqa: BLE001
                    await self.order_repo.session.rollback()
                    return False
                return True

        try:
            await self._unreserve_payload(order_id, pending.items)
        except Exception as exc:  # noqa: BLE001 - preserve COMPENSATING
            logger.exception("Failed to retry checkout reserve compensation %s", order_id)
            await self.order_repo.queue_reservation_compensation(
                order_id=order_id,
                items=pending.items,
                error=f"unreserve: {type(exc).__name__}: {exc}",
                next_retry_at=self._next_retry_at(pending.attempts + 1),
            )
            try:
                await self.order_repo.session.commit()
            except Exception:  # noqa: BLE001 - prior COMPENSATING is durable
                await self.order_repo.session.rollback()
            return False

        await self.order_repo.mark_reservation_compensated(
            pending, when=datetime.now(timezone.utc)
        )
        try:
            # Never delegate the final durability boundary to the lifecycle
            # worker's outer transaction: process death here is precisely the
            # failure mode this state machine closes.
            await self.order_repo.session.commit()
        except Exception:  # noqa: BLE001 - durable COMPENSATING permits safe replay
            await self.order_repo.session.rollback()
            return False
        return True

    @staticmethod
    def _compensation_state(pending: object) -> CheckoutCompensationState:
        state_value = getattr(pending, "compensation_state", None)
        if isinstance(state_value, CheckoutCompensationState):
            return state_value
        if state_value is not None:
            return CheckoutCompensationState(state_value)
        # Compatibility for a row created by the migration immediately before
        # this state was introduced; the migration itself backfills all rows.
        return (
            CheckoutCompensationState.COMPENSATED
            if getattr(pending, "compensated_at", None) is not None
            else CheckoutCompensationState.PENDING
        )

    @classmethod
    def _is_compensation_complete(cls, pending: object) -> bool:
        return cls._compensation_state(pending) is CheckoutCompensationState.COMPENSATED

    @classmethod
    def _raise_if_checkout_operation_compensating(cls, pending: object) -> None:
        if cls._compensation_state(pending) in {
            CheckoutCompensationState.COMPENSATING,
            CheckoutCompensationState.COMPENSATED,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "CHECKOUT_OPERATION_COMPENSATED",
                    "message": "Checkout reservation was already compensated",
                },
            )

    @staticmethod
    def _checkout_operation_id(user_id: UUID, idempotency_key: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"neomarket:checkout:{user_id}:{idempotency_key}")

    @staticmethod
    def _validate_checkout_intent(pending: object, request_fingerprint: str) -> None:
        stored = getattr(pending, "request_fingerprint", None)
        if stored is not None and stored != request_fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "Idempotency key was already used with a different request body",
                },
            )

    @staticmethod
    def _next_retry_at(attempt: int) -> datetime:
        delay = min(
            CANCEL_RETRY_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
            CANCEL_RETRY_MAX_SECONDS,
        )
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

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
        if isinstance(detail, dict) and isinstance(detail.get("details"), dict):
            detail = {**detail, **detail["details"]}
        if isinstance(detail, dict) and "failed_items" in detail:
            return {
                # B2C exposes its own checkout failure code while preserving
                # B2B's exact problematic SKU list.
                "code": "RESERVE_FAILED",
                "message": "Unable to reserve one or more items",
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
        address: object | None = None,
    ) -> dict[str, object]:
        if order_request is None or address is None:
            raise RuntimeError("Checkout requires a validated delivery address")
        fields = (
            "id", "country", "region", "city", "street", "building",
            "apartment", "postal_code", "recipient_name", "recipient_phone",
            "is_default", "comment", "created_at",
        )
        snapshot = {name: getattr(address, name, None) for name in fields}
        snapshot["id"] = str(snapshot["id"])
        if snapshot["created_at"] is not None:
            snapshot["created_at"] = snapshot["created_at"].isoformat()
        return snapshot

    def _b2b_unavailable(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "B2B_UNAVAILABLE",
                "message": "B2B service is temporarily unavailable",
            },
        )

    def _sync_order_address(self, order: Order) -> None:
        address_id = getattr(order, "address_id", None)
        if address_id is None:
            return
        address = dict(getattr(order, "address", None) or {})
        address["id"] = str(address_id)
        order.address = address

    async def _load_order_for_response(self, order_id: UUID) -> Order:
        """Return the aggregate with every relationship read by OrderResponse."""
        order = await self.order_repo.get_with_items(order_id)
        if order is None:
            raise RuntimeError("Updated order could not be reloaded")
        return order

    def _request_fingerprint(
        self,
        order_request: OrderCreateRequest | None,
    ) -> str:
        payload = (
            order_request.model_dump(mode="json")
            if order_request is not None
            else {}
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _return_idempotent_order(
        self,
        existing: Order,
        request_fingerprint: str,
    ) -> Order:
        stored_fingerprint = self._stored_request_fingerprint(existing)
        if stored_fingerprint and stored_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "Idempotency key was already used with a different request body",
                },
            )
        self.last_checkout_replayed = True
        return existing

    def _stored_request_fingerprint(self, order: Order) -> str | None:
        stored = getattr(order, "request_fingerprint", None)
        if stored:
            return stored
        address_id = getattr(order, "address_id", None)
        payment_method_id = getattr(order, "payment_method_id", None)
        if address_id is None and payment_method_id is None:
            return self._request_fingerprint(None)
        payload = {
            "address_id": str(address_id) if address_id is not None else None,
            "payment_method_id": (
                str(payment_method_id) if payment_method_id is not None else None
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
