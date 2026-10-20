from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.order import CheckoutCompensationState, OrderStatus
from src.models.user import User
from src.schemas.order import (
    CheckoutAttemptResponse,
    OrderCreateRequest,
    CancelOrderRequest,
    OrderPaginatedResponse,
    OrderResponse,
    CheckoutOperationStatus,
)
from src.repositories.order_repo import OrderRepository
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


@router.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    status_code=201,
    responses={
        200: {"model": OrderResponse, "description": "Idempotent replay"},
        400: {"description": "Invalid checkout request"},
        401: {"description": "Unauthorized"},
        409: {"description": "Reserve or idempotency conflict"},
        422: {"description": "Cart validation failed"},
        503: {"description": "B2B unavailable"},
        202: {"model": OrderResponse, "description": "Checkout accepted for asynchronous completion"},
    },
)
@router.post("/orders", response_model=OrderResponse, status_code=201, include_in_schema=False)
async def create_order(
    order_request: OrderCreateRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    x_session_id: UUID | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    key = str(idempotency_key)
    cart = await CartService(db).get_or_create_cart(
        user=current_user,
        session_id=str(x_session_id) if x_session_id else None,
    )
    if order_request.cart_id is not None and order_request.cart_id != cart.id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CART_NOT_OWNED",
                "message": "Checkout cart does not belong to the current buyer",
            },
        )
    service = OrderService(db)
    order = await service.checkout(
        current_user.id,
        cart.id,
        idempotency_key=key,
        order_request=order_request,
    )
    payload = OrderResponse.model_validate(order).model_dump(mode="json")
    return JSONResponse(
        # OpenAPI distinguishes a newly-created order from an idempotent replay.
        status_code=200 if service.last_checkout_replayed else 201,
        content=payload,
    )


@router.get("/api/v1/orders/{order_id}", response_model=OrderResponse)
@router.get("/orders/{order_id}", response_model=OrderResponse, include_in_schema=False)
async def get_order(
    order_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    return await OrderService(db).get_order(order_id, current_user.id)


@router.get(
    "/api/v1/checkout-operations/by-idempotency",
    response_model=CheckoutOperationStatus,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def get_checkout_operation_by_idempotency(
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutOperationStatus:
    """Resolve an ambiguous checkout write without creating a new attempt.

    The browser keeps one UUID for the logical submit.  If a proxy timeout
    hides the POST response, the buyer can safely resolve the deterministic
    operation using the same key; no new order or reservation is created.
    """
    operation_id = OrderService._checkout_operation_id(current_user.id, str(idempotency_key))
    attempt = await OrderRepository(db).get_checkout_attempt(operation_id, current_user.id)
    if attempt is not None:
        return CheckoutOperationStatus(
            operation_id=attempt.attempt_id,
            state=attempt.status,
            order_id=attempt.order_id,
            updated_at=attempt.updated_at,
            attempt_id=attempt.attempt_id,
            idempotency_key=UUID(attempt.idempotency_key),
            error_code=attempt.error_code,
        )
    order, pending = await OrderRepository(db).get_checkout_operation(operation_id, current_user.id)
    if order is not None:
        return CheckoutOperationStatus(
            operation_id=operation_id,
            state="COMPLETED",
            order_id=order.id,
            updated_at=order.updated_at,
        )
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHECKOUT_OPERATION_NOT_FOUND", "message": "Checkout operation not found"},
        )
    if pending.compensation_state is CheckoutCompensationState.COMPENSATED:
        state = "FAILED"
    elif pending.compensation_state is CheckoutCompensationState.COMPENSATING:
        state = "RECONCILE_REQUIRED"
    else:
        state = "PENDING"
    return CheckoutOperationStatus(
        operation_id=operation_id,
        state=state,
        updated_at=pending.updated_at,
    )


@router.get(
    "/api/v1/checkout-operations/{operation_id}",
    response_model=CheckoutOperationStatus,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def get_checkout_operation(
    operation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutOperationStatus:
    repository = OrderRepository(db)
    attempt = await repository.get_checkout_attempt(operation_id, current_user.id)
    if attempt is not None:
        return CheckoutOperationStatus(
            operation_id=attempt.attempt_id,
            state=attempt.status,
            order_id=attempt.order_id,
            updated_at=attempt.updated_at,
            attempt_id=attempt.attempt_id,
            idempotency_key=UUID(attempt.idempotency_key),
            error_code=attempt.error_code,
        )
    order, pending = await repository.get_checkout_operation(
        operation_id, current_user.id
    )
    if order is not None:
        return CheckoutOperationStatus(
            operation_id=operation_id,
            state="COMPLETED",
            order_id=order.id,
            updated_at=order.updated_at,
        )
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHECKOUT_OPERATION_NOT_FOUND", "message": "Checkout operation not found"},
        )
    if pending.compensation_state is CheckoutCompensationState.COMPENSATED:
        state = "FAILED"
    elif pending.compensation_state is CheckoutCompensationState.COMPENSATING:
        state = "RECONCILE_REQUIRED"
    else:
        state = "PENDING"
    return CheckoutOperationStatus(
        operation_id=operation_id,
        state=state,
        updated_at=pending.updated_at,
    )


@router.get(
    "/api/v1/checkout-attempts/{attempt_id}",
    response_model=CheckoutAttemptResponse,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def get_checkout_attempt(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutAttemptResponse:
    attempt = await OrderRepository(db).get_checkout_attempt(attempt_id, current_user.id)
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHECKOUT_ATTEMPT_NOT_FOUND", "message": "Checkout attempt not found"},
        )
    return CheckoutAttemptResponse(
        attempt_id=attempt.attempt_id,
        idempotency_key=UUID(attempt.idempotency_key),
        status=attempt.status,
        order_id=attempt.order_id,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
        error_code=attempt.error_code,
    )


@router.post(
    "/api/v1/orders/{order_id}/cancel",
    response_model=OrderResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Order not found"},
        409: {"description": "Order status does not allow cancellation"},
        202: {"model": OrderResponse, "description": "Cancellation accepted for asynchronous completion"},
    },
)
@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderResponse,
    include_in_schema=False,
)
async def cancel_order(
    order_id: UUID,
    cancel_request: CancelOrderRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order = await OrderService(db).cancel_order(
        order_id,
        current_user.id,
        reason=cancel_request.reason if cancel_request else None,
    )
    return order
