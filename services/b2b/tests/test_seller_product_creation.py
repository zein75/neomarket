from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.models.seller_product_creation import SellerProductCreation
from src.schemas.product import ProductWithFirstSKUCreate
from src.services.product_service import ProductService


class ProductRepositoryStub:
    def __init__(self, product) -> None:
        self.product = product

    async def get_with_skus(self, product_id):
        return self.product if self.product.id == product_id else None


class DraftLookupSession:
    def __init__(self, receipt) -> None:
        self.receipt = receipt
        self.statement = None

    async def scalar(self, statement):
        self.statement = statement
        return self.receipt


@pytest.mark.asyncio
async def test_atomic_product_creation_replay_is_owner_scoped() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    product = SimpleNamespace(id=product_id, seller_id=seller_id, skus=[object()])
    service = ProductService.__new__(ProductService)
    service.repo = ProductRepositoryStub(product)
    receipt = SellerProductCreation(
        seller_id=seller_id,
        idempotency_key="request-key",
        request_hash="a" * 64,
        product_id=product_id,
    )

    result = await service._replay_product_creation(receipt, "a" * 64)

    assert result is product
    assert {column.name for column in SellerProductCreation.__table__.primary_key} == {
        "seller_id",
        "idempotency_key",
    }


@pytest.mark.asyncio
async def test_atomic_product_creation_rejects_key_reuse_with_new_payload() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    service = ProductService.__new__(ProductService)
    service.repo = ProductRepositoryStub(
        SimpleNamespace(id=product_id, seller_id=seller_id, skus=[])
    )
    receipt = SellerProductCreation(
        seller_id=seller_id,
        idempotency_key="request-key",
        request_hash="a" * 64,
        product_id=product_id,
    )

    with pytest.raises(HTTPException) as error:
        await service._replay_product_creation(receipt, "b" * 64)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_draft_operation_lookup_recovers_product_after_lost_response() -> None:
    seller_id = uuid4()
    product_id = uuid4()
    operation_id = uuid4()
    sku_id = uuid4()
    product = SimpleNamespace(
        id=product_id,
        seller_id=seller_id,
        revision=3,
        skus=[SimpleNamespace(
            id=sku_id,
            seller_article="KB-1",
            name="Keyboard",
            price=129900,
            currency="RUB",
            on_hand=4,
            stock=4,
            options={"color": "black"},
        )],
    )
    receipt = SellerProductCreation(
        seller_id=seller_id,
        idempotency_key=str(uuid4()),
        request_hash="a" * 64,
        product_id=product_id,
        operation_id=operation_id,
    )
    session = DraftLookupSession(receipt)
    service = ProductService.__new__(ProductService)
    service.repo = ProductRepositoryStub(product)
    service.repo.session = session

    result = await service.get_draft_by_idempotency_key(seller_id, receipt.idempotency_key)

    assert result.id == product_id
    assert result.operation_id == operation_id
    assert result.variants[0].id == sku_id


@pytest.mark.asyncio
async def test_draft_operation_lookup_returns_not_found_without_receipt() -> None:
    service = ProductService.__new__(ProductService)
    service.repo = ProductRepositoryStub(SimpleNamespace(id=uuid4(), seller_id=uuid4(), skus=[]))
    service.repo.session = DraftLookupSession(None)

    with pytest.raises(HTTPException) as error:
        await service.get_draft_by_idempotency_key(uuid4(), str(uuid4()))

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "DRAFT_OPERATION_NOT_FOUND"


def test_atomic_product_creation_contract_requires_product_and_first_sku() -> None:
    command = ProductWithFirstSKUCreate.model_validate(
        {
            "product": {
                "title": "Test",
                "description": "Test product",
                "category_id": str(uuid4()),
                "images": [{"url": "https://example.com/product.png"}],
            },
            "first_sku": {
                "name": "Test SKU",
                "price": 100,
                "stock": 3,
                "images": [{"url": "https://example.com/sku.png"}],
            },
        }
    )
    assert command.first_sku.stock == 3
    with pytest.raises(ValueError):
        ProductWithFirstSKUCreate.model_validate({"product": command.product.model_dump()})
