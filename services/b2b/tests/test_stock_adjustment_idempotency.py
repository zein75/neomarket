from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.models.stock_adjustment import StockAdjustment
from src.services.sku_service import SKUService


class ExistingAdjustmentSession:
    def __init__(self, adjustment: StockAdjustment) -> None:
        self.adjustment = adjustment

    async def scalar(self, _statement):
        return self.adjustment


class ExistingAdjustmentSKURepository:
    def __init__(self, session) -> None:
        self.session = session
        self.sku = SimpleNamespace(
            id=session.adjustment.sku_id,
            product=SimpleNamespace(seller_id=session.adjustment.seller_id),
            stock=99,
            on_hand=99,
            reserved_quantity=4,
        )

    async def get_with_product(self, sku_id):
        return self.sku if sku_id == self.sku.id else None


@pytest.mark.asyncio
async def test_replay_returns_saved_result_without_changing_persisted_sku(monkeypatch) -> None:
    seller_id = uuid4()
    sku_id = uuid4()
    adjustment = StockAdjustment(
        sku_id=sku_id,
        delta=3,
        reason="cycle count",
        seller_id=seller_id,
        idempotency_key="key-1",
        request_hash=SKUService._stock_adjustment_hash(
            sku_id=sku_id, seller_id=seller_id, delta=3, reason="cycle count"
        ),
        result_on_hand=14,
        result_reserved=4,
    )
    session = ExistingAdjustmentSession(adjustment)
    repo = ExistingAdjustmentSKURepository(session)
    monkeypatch.setattr("src.services.sku_service.SKURepository", lambda _: repo)
    monkeypatch.setattr("src.services.sku_service.ProductRepository", lambda _: object())

    result, result_on_hand, result_reserved = await SKUService(session).adjust_stock(
        sku_id,
        seller_id,
        SimpleNamespace(delta=3, reason="cycle count"),
        "key-1",
    )

    assert result_on_hand == 14
    assert result_reserved == 4
    assert repo.sku.stock == 99
    assert repo.sku.on_hand == 99


@pytest.mark.asyncio
async def test_reusing_key_for_another_payload_returns_conflict(monkeypatch) -> None:
    seller_id = uuid4()
    sku_id = uuid4()
    adjustment = StockAdjustment(
        sku_id=sku_id,
        delta=3,
        reason="cycle count",
        seller_id=seller_id,
        idempotency_key="key-1",
        request_hash=SKUService._stock_adjustment_hash(
            sku_id=sku_id, seller_id=seller_id, delta=3, reason="cycle count"
        ),
        result_on_hand=14,
        result_reserved=4,
    )
    session = ExistingAdjustmentSession(adjustment)
    monkeypatch.setattr(
        "src.services.sku_service.SKURepository",
        lambda _: ExistingAdjustmentSKURepository(session),
    )
    monkeypatch.setattr("src.services.sku_service.ProductRepository", lambda _: object())

    with pytest.raises(HTTPException) as error:
        await SKUService(session).adjust_stock(
            sku_id,
            seller_id,
            SimpleNamespace(delta=4, reason="cycle count"),
            "key-1",
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
