from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.reservation import ReserveRequest
from src.schemas.sku import SKUCreate


def test_inventory_write_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReserveRequest(
            order_id=uuid4(),
            idempotency_key=uuid4(),
            items=[{"sku_id": uuid4(), "quantity": 1}],
            is_admin=True,
        )


def test_inventory_write_schema_caps_quantity_and_item_count() -> None:
    with pytest.raises(ValidationError):
        ReserveRequest(
            order_id=uuid4(),
            idempotency_key=uuid4(),
            items=[{"sku_id": uuid4(), "quantity": 101}],
        )


def test_sku_stock_cannot_be_negative_or_have_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SKUCreate(
            product_id=uuid4(),
            name="SKU",
            price=1,
            stock=-1,
            images=[{"url": "https://cdn.example/item.jpg"}],
        )
