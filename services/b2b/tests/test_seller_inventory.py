from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routers.seller_inventory import _decode_cursor, _encode_cursor
from src.schemas.inventory import SellerDashboardMetrics, SellerInventoryResponse


def test_inventory_cursor_is_signed_and_bound_to_seller() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    sku_id = uuid4()

    cursor = _encode_cursor(seller_id, product_id, sku_id, "blue", "available")

    assert _decode_cursor(cursor, seller_id, "blue", "available") == (product_id, sku_id)
    with pytest.raises(HTTPException) as foreign:
        _decode_cursor(cursor, uuid4(), "blue", "available")
    assert foreign.value.status_code == 422
    with pytest.raises(HTTPException) as wrong_filter:
        _decode_cursor(cursor, seller_id, "red", "available")
    assert wrong_filter.value.status_code == 422
    with pytest.raises(HTTPException) as tampered:
        _decode_cursor(cursor[:-1] + ("A" if cursor[-1] != "A" else "B"), seller_id, "blue", "available")
    assert tampered.value.status_code == 422
    with pytest.raises(HTTPException) as malformed:
        _decode_cursor("not-a-cursor", seller_id)
    assert malformed.value.status_code == 422


def test_inventory_response_carries_a_bounded_page() -> None:
    product_id = uuid4()
    sku_id = uuid4()
    response = SellerInventoryResponse.model_validate(
        {
            "items": [
                {
                    "sku_id": sku_id,
                    "product_id": product_id,
                    "product_title": "Seller product",
                    "sku_name": "Blue / M",
                    "status": "MODERATED",
                    "category": "Storage",
                    "stock_quantity": 12,
                    "reserved_quantity": 3,
                    "active_quantity": 9,
                    "is_active": True,
                    "revision": 4,
                }
            ],
            "page": {"has_more": True, "next_cursor": "signed-cursor"},
        }
    )

    assert response.items[0].active_quantity == 9
    assert response.page["has_more"] is True


def test_dashboard_metrics_are_server_defined_and_timestamped() -> None:
    response = SellerDashboardMetrics.model_validate(
        {
            "as_of": "2026-10-16T12:00:00Z",
            "metrics": {
                "live_products": 180,
                "sku_count": 120000,
                "total_on_hand": 450000,
                "available_stock": 448800,
                "pending_moderation": 6,
                "reserved_stock": 1200,
            },
            "definitions": {"available_stock": "On hand minus reserved"},
        }
    )
    assert response.metrics["sku_count"] == 120000
    assert response.metrics["available_stock"] == 448800
