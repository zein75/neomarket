from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from src.schemas.product import (
    DraftVariantInput,
    FirstSKUCreate,
    ProductCreate,
    ProductDraftCreate,
    ProductUpdate,
    ProductWithFirstSKUCreate,
)
from src.schemas.sku import SKUCreate, SKUPatch, SKUUpdate, StockAdjustmentRequest


UNTRUSTED_FIELDS: Mapping[str, Any] = {
    "seller_id": str(uuid4()),
    "status": "MODERATED",
    "reserved": 5,
    "balance": 100_000,
}


def _assert_untrusted_fields_rejected(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    for field, value in UNTRUSTED_FIELDS.items():
        with pytest.raises(ValidationError):
            model.model_validate({**payload, field: value})


def test_product_create_and_update_reject_control_plane_fields() -> None:
    category_id = str(uuid4())
    image = {"url": "https://cdn.neomarket.test/item.webp"}
    _assert_untrusted_fields_rejected(
        ProductCreate,
        {
            "title": "Test item",
            "description": "Test description",
            "category_id": category_id,
            "images": [image],
        },
    )
    _assert_untrusted_fields_rejected(ProductUpdate, {"title": "Updated item"})


def test_atomic_and_draft_product_models_reject_control_plane_fields() -> None:
    category_id = str(uuid4())
    image = {"url": "https://cdn.neomarket.test/item.webp"}
    product = {
        "title": "Test item",
        "description": "Test description",
        "category_id": category_id,
        "images": [image],
    }
    first_sku = {"name": "First variant", "price": 100, "stock": 0, "images": [image]}
    _assert_untrusted_fields_rejected(
        ProductWithFirstSKUCreate,
        {"product": product, "first_sku": first_sku},
    )
    _assert_untrusted_fields_rejected(FirstSKUCreate, first_sku)

    variant = {
        "seller_article": "TEST-1",
        "name": "Test variant",
        "price_minor": 100,
        "currency": "RUB",
        "on_hand": 0,
    }
    _assert_untrusted_fields_rejected(
        ProductDraftCreate,
        {"title": "Test item", "description": "Test description", "category_id": category_id, "variants": [variant]},
    )
    _assert_untrusted_fields_rejected(DraftVariantInput, variant)


def test_sku_and_stock_models_reject_control_plane_fields() -> None:
    image = {"url": "https://cdn.neomarket.test/item.webp"}
    _assert_untrusted_fields_rejected(
        SKUCreate,
        {"product_id": str(uuid4()), "name": "Test SKU", "price": 100, "images": [image]},
    )
    _assert_untrusted_fields_rejected(SKUUpdate, {"name": "Updated SKU"})
    _assert_untrusted_fields_rejected(SKUPatch, {"name": "Updated SKU"})
    _assert_untrusted_fields_rejected(StockAdjustmentRequest, {"delta": 1, "reason": "cycle count"})
