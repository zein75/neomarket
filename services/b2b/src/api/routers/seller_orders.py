import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from src.api.deps import (
    get_db,
    require_seller_permission,
    verify_service_key,
)
from src.core.config import settings
from src.models.seller import Seller
from src.schemas.seller_order import (
    SellerOrderAllocationEvent,
    SellerOrderCancellationEvent,
    CarrierWebhookResponse,
    LocalCarrierWebhookEvent,
    SellerOrderListResponse,
    SellerOrderResponse,
    SellerPackingCreate,
    SellerCarrierOperationResponse,
    SellerShipmentResponse,
)
from src.services.seller_order_service import SellerOrderService
from src.services.local_carrier_webhook_service import LocalCarrierWebhookService


router = APIRouter(tags=["seller-orders"])


def _raise_commercial_flow_disabled(flow: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "COMMERCIAL_FLOW_DISABLED",
            "message": "Seller fulfillment actions are disabled until commercial policy is approved",
            "flow": flow,
            "feature_status": "disabled_pending_adr",
        },
    )


def _encode_cursor(seller_id: UUID, allocated_at: datetime, order_id: UUID) -> str:
    payload = json.dumps(
        {"seller_id": str(seller_id), "allocated_at": allocated_at.isoformat(), "id": str(order_id)},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()
    return f"{base64.urlsafe_b64encode(payload).decode().rstrip('=')}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _decode_cursor(cursor: str | None, seller_id: UUID) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        encoded, signed = cursor.split(".", 1)
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        signature = base64.urlsafe_b64decode(signed + "=" * (-len(signed) % 4))
        expected = hmac.new(settings.secret_key.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad cursor signature")
        payload = json.loads(raw)
        if UUID(payload["seller_id"]) != seller_id:
            raise ValueError("cursor belongs to another seller")
        allocated_at = datetime.fromisoformat(payload["allocated_at"])
        if allocated_at.tzinfo is None:
            raise ValueError("cursor timestamp must include timezone")
        return allocated_at, UUID(payload["id"])
    except (ValueError, TypeError, KeyError, binascii.Error, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURSOR", "message": "Seller order cursor is invalid"},
        ) from exc


@router.post("/internal/v1/seller-orders/allocations", status_code=status.HTTP_202_ACCEPTED)
async def receive_seller_allocation(
    event: SellerOrderAllocationEvent,
    response: Response,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    created = await SellerOrderService(db).receive_allocation(event)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return {"accepted": created}


@router.post("/internal/v1/seller-orders/cancellations", status_code=status.HTTP_202_ACCEPTED)
async def receive_seller_cancellation(
    event: SellerOrderCancellationEvent,
    response: Response,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    created = await SellerOrderService(db).receive_cancellation(event)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return {"accepted": created}


@router.post(
    "/internal/v1/carriers/local-test/webhook",
    response_model=CarrierWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_local_carrier_webhook(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CarrierWebhookResponse:
    if settings.app_env.lower() not in {"local", "dev", "development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LOCAL_CARRIER_WEBHOOK_DISABLED", "message": "Local carrier webhook is disabled"},
        )
    body = await request.body()
    supplied = request.headers.get("X-Local-Carrier-Signature", "")
    expected = "sha256=" + hmac.new(
        settings.local_carrier_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CARRIER_SIGNATURE", "message": "Carrier signature is invalid"},
        )
    try:
        event = LocalCarrierWebhookEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_CARRIER_EVENT", "message": "Carrier event is invalid"},
        ) from exc
    result, created = await LocalCarrierWebhookService(db).receive(event)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/api/v1/seller/orders", response_model=SellerOrderListResponse)
async def list_seller_orders(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1024),
    seller: Seller = Depends(require_seller_permission("orders.read")),
    db: AsyncSession = Depends(get_db),
) -> SellerOrderListResponse:
    service = SellerOrderService(db)
    decoded = _decode_cursor(cursor, seller.id)
    orders = await service.list_for_seller(seller.id, limit=limit, cursor=decoded)
    has_more = len(orders) > limit
    orders = orders[:limit]
    next_cursor = (
        _encode_cursor(seller.id, orders[-1].allocated_at, orders[-1].id)
        if has_more and orders
        else None
    )
    return SellerOrderListResponse(
        items=orders,
        page={"has_more": has_more, "next_cursor": next_cursor},
        as_of=datetime.now(timezone.utc),
    )


@router.get("/api/v1/seller/orders/{seller_order_id}", response_model=SellerOrderResponse)
async def get_seller_order(
    seller_order_id: UUID,
    seller: Seller = Depends(require_seller_permission("orders.read")),
    db: AsyncSession = Depends(get_db),
) -> SellerOrderResponse:
    order = await SellerOrderService(db).get_for_seller(seller.id, seller_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SELLER_ORDER_NOT_FOUND", "message": "Seller order not found"},
        )
    return SellerOrderResponse.model_validate(order)


@router.post("/api/v1/seller/orders/{seller_order_id}/accept", response_model=SellerOrderResponse)
async def accept_seller_order(
    seller_order_id: UUID,
    seller: Seller = Depends(require_seller_permission("orders.fulfill")),
    db: AsyncSession = Depends(get_db),
) -> SellerOrderResponse:
    _raise_commercial_flow_disabled("seller_order_acceptance")


@router.post(
    "/api/v1/seller/orders/{seller_order_id}/shipments",
    response_model=SellerShipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_seller_packed_shipment(
    seller_order_id: UUID,
    request: SellerPackingCreate,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("orders.fulfill")),
    db: AsyncSession = Depends(get_db),
) -> SellerShipmentResponse:
    _raise_commercial_flow_disabled("seller_packing_manifest")


@router.post(
    "/api/v1/seller/orders/{seller_order_id}/shipments/{shipment_id}/dispatch",
    response_model=SellerCarrierOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_seller_shipment_to_local_simulator(
    seller_order_id: UUID,
    shipment_id: UUID,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("orders.fulfill")),
    db: AsyncSession = Depends(get_db),
) -> SellerCarrierOperationResponse:
    _raise_commercial_flow_disabled("seller_carrier_dispatch")


@router.get(
    "/api/v1/seller/orders/{seller_order_id}/shipments/{shipment_id}/carrier-operation",
    response_model=SellerCarrierOperationResponse,
)
async def get_seller_carrier_operation(
    seller_order_id: UUID,
    shipment_id: UUID,
    seller: Seller = Depends(require_seller_permission("orders.read")),
    db: AsyncSession = Depends(get_db),
) -> SellerCarrierOperationResponse:
    operation = await SellerOrderService(db).get_carrier_operation(
        seller.id,
        seller_order_id,
        shipment_id,
    )
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CARRIER_OPERATION_NOT_FOUND", "message": "Carrier operation not found"},
        )
    return SellerCarrierOperationResponse.model_validate(operation)
