from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.models.product import ProductStatus
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services import invoice_service as invoice_service_module
from src.services.invoice_service import InvoiceService


class FakeSession:
    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


def _sku(*, seller_id, status=ProductStatus.MODERATED):
    product = SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id,
        status=status,
        deleted=False,
    )
    return SimpleNamespace(
        id=uuid4(),
        product_id=product.id,
        product=product,
    )


class FakeSKURepository:
    skus: dict[object, object] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_with_product(self, sku_id):
        return self.skus.get(sku_id)


class FakeInvoiceRepository:
    created = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def create_invoice(self, *, seller_id, items):
        invoice = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            status="PENDING",
            items=[
                SimpleNamespace(
                    sku_id=item.sku_id,
                    quantity=item.quantity,
                    accepted_quantity=None,
                )
                for item in items
            ],
        )
        self.__class__.created = invoice
        return invoice


@pytest.fixture(autouse=True)
def patch_repositories(monkeypatch: pytest.MonkeyPatch):
    FakeSKURepository.skus = {}
    FakeInvoiceRepository.created = None
    monkeypatch.setattr(invoice_service_module, "SKURepository", FakeSKURepository)
    monkeypatch.setattr(
        invoice_service_module, "InvoiceRepository", FakeInvoiceRepository
    )


def _invoice_data(sku_id, quantity: int = 5) -> InvoiceCreate:
    return InvoiceCreate(
        items=[
            InvoiceItemCreate(
                sku_id=sku_id,
                quantity=quantity,
            )
        ]
    )


def test_invoice_create_accepts_openapi_invoice_items_alias() -> None:
    sku_id = uuid4()

    data = InvoiceCreate.model_validate(
        {
            "invoice_items": [
                {
                    "sku_id": str(sku_id),
                    "quantity": 5,
                }
            ]
        }
    )

    assert data.items[0].sku_id == sku_id


@pytest.mark.asyncio
async def test_create_invoice_with_moderated_sku_returns_201() -> None:
    seller_id = uuid4()
    sku = _sku(seller_id=seller_id)
    FakeSKURepository.skus = {sku.id: sku}

    invoice = await InvoiceService(FakeSession()).create(
        seller_id,
        _invoice_data(sku.id),
    )

    assert invoice.status == "PENDING"
    assert invoice.seller_id == seller_id
    assert invoice.items[0].sku_id == sku.id
    assert invoice.items[0].quantity == 5
    assert invoice.items[0].accepted_quantity is None


@pytest.mark.asyncio
async def test_empty_items_returns_400() -> None:
    with pytest.raises(Exception) as exc_info:
        await InvoiceService(FakeSession()).create(
            uuid4(),
            InvoiceCreate(items=[]),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_non_moderated_sku_returns_400() -> None:
    seller_id = uuid4()
    sku = _sku(seller_id=seller_id, status=ProductStatus.ON_MODERATION)
    FakeSKURepository.skus = {sku.id: sku}

    with pytest.raises(Exception) as exc_info:
        await InvoiceService(FakeSession()).create(
            seller_id,
            _invoice_data(sku.id),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_others_sku_returns_403() -> None:
    sku = _sku(seller_id=uuid4())
    FakeSKURepository.skus = {sku.id: sku}

    with pytest.raises(Exception) as exc_info:
        await InvoiceService(FakeSession()).create(
            uuid4(),
            _invoice_data(sku.id),
        )

    assert exc_info.value.status_code == 403
