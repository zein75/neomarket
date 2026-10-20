from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from src.api.routers.seller_orders import (
    _decode_cursor,
    _encode_cursor,
    accept_seller_order,
    create_seller_packed_shipment,
    dispatch_seller_shipment_to_local_simulator,
)
from src.schemas.seller_order import SellerOrderAllocationEvent, SellerOrderResponse


def test_seller_order_cursor_is_signed_and_tenant_bound() -> None:
    seller_id = uuid4()
    allocated_at = datetime.now(timezone.utc)
    order_id = uuid4()

    cursor = _encode_cursor(seller_id, allocated_at, order_id)

    assert _decode_cursor(cursor, seller_id) == (allocated_at, order_id)
    with pytest.raises(HTTPException) as foreign:
        _decode_cursor(cursor, uuid4())
    assert foreign.value.status_code == 422
    with pytest.raises(HTTPException) as tampered:
        _decode_cursor(("A" if cursor[0] != "A" else "B") + cursor[1:], seller_id)
    assert tampered.value.status_code == 422


def test_allocation_contract_has_minimal_seller_snapshot_and_money_in_minor_units() -> None:
    seller_id = uuid4()
    buyer_order_id = uuid4()
    seller_order_id = uuid4()
    event = SellerOrderAllocationEvent.model_validate(
        {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "event_type": "seller_order.allocated.v1",
            "producer": "b2c",
            "aggregate_type": "seller_order",
            "aggregate_id": str(seller_order_id),
            "aggregate_version": 1,
            "tenant_id": str(seller_id),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(buyer_order_id),
            "payload_hash": "0" * 64,
            "payload": {
                "buyer_order_id": str(buyer_order_id),
                "seller_order_id": str(seller_order_id),
                "seller_id": str(seller_id),
                "currency": "RUB",
                "status": "CREATED",
                "total_minor": 2500,
                "items": [
                    {
                        "sku_id": str(uuid4()),
                        "product_id": str(uuid4()),
                        "product_title": "Snapshot product",
                        "sku_name": "Variant",
                        "quantity": 1,
                        "unit_price_minor": 2500,
                        "line_total_minor": 2500,
                    }
                ],
            },
        }
    )
    snapshot = event.payload.model_dump()
    assert snapshot["seller_id"] == seller_id
    assert snapshot["status"] == "CREATED"
    assert "contact" not in snapshot and "address" not in snapshot and "buyer_id" not in snapshot
    assert event.payload.items[0].quantity * event.payload.items[0].unit_price_minor == event.payload.total_minor
    assert "buyer_order_id" not in SellerOrderResponse.model_fields


def test_commercial_fulfillment_routes_are_disabled_until_adr() -> None:
    async def check_routes() -> None:
        routes = (
            (accept_seller_order, (uuid4(), None, None), "seller_order_acceptance"),
            (create_seller_packed_shipment, (uuid4(), None, Response(), uuid4(), None, None), "seller_packing_manifest"),
            (dispatch_seller_shipment_to_local_simulator, (uuid4(), uuid4(), Response(), uuid4(), None, None), "seller_carrier_dispatch"),
        )
        for route, arguments, flow in routes:
            with pytest.raises(HTTPException) as disabled:
                await route(*arguments)
            assert disabled.value.status_code == 503
            assert disabled.value.detail["code"] == "COMMERCIAL_FLOW_DISABLED"
            assert disabled.value.detail["flow"] == flow
            assert disabled.value.detail["feature_status"] == "disabled_pending_adr"

    import asyncio

    asyncio.run(check_routes())

