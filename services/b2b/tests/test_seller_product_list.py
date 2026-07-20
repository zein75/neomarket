from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.main import app
from src.models.product import ProductStatus
from src.services import product_service as product_service_module
from src.services.product_service import ProductService


def _sku(*, stock: int = 10, reserved_quantity: int = 2):
    return SimpleNamespace(stock=stock, reserved_quantity=reserved_quantity)


def _product(
    *,
    seller_id: UUID,
    title: str = "Wireless Keyboard",
    status: ProductStatus | str = ProductStatus.MODERATED,
    deleted: bool = False,
    skus: list[SimpleNamespace] | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id,
        title=title,
        description="Low-profile keyboard",
        category_id=uuid4(),
        images=["https://cdn.neomarket.test/products/keyboard.jpg"],
        characteristics={"layout": "US"},
        status=status,
        category=None,
        is_active=not deleted,
        deleted=deleted,
        skus=skus or [_sku()],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class FakeProductRepository:
    products: list[SimpleNamespace] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_for_seller_cabinet(
        self,
        *,
        seller_id,
        limit,
        offset,
        status=None,
        include_deleted=False,
        search=None,
    ):
        products = [product for product in self.products if product.seller_id == seller_id]
        if not include_deleted:
            products = [product for product in products if not product.deleted]
        if status:
            products = [product for product in products if str(product.status) == status]
        if search:
            lowered = search.lower()
            products = [product for product in products if lowered in product.title.lower()]

        total = len(products)
        page = products[offset : offset + limit]
        return [
            (
                product,
                len(product.skus),
                sum(sku.stock - sku.reserved_quantity for sku in product.skus),
            )
            for product in page
        ], total


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch: pytest.MonkeyPatch):
    FakeProductRepository.products = []
    monkeypatch.setattr(
        product_service_module, "ProductRepository", FakeProductRepository
    )


@pytest.mark.asyncio
async def test_list_returns_only_own_products() -> None:
    seller_id = uuid4()
    own = _product(seller_id=seller_id, skus=[_sku(stock=10, reserved_quantity=3)])
    other = _product(seller_id=uuid4())
    FakeProductRepository.products = [own, other]

    body = await ProductService(SimpleNamespace()).list_for_seller_cabinet(
        seller_id=seller_id
    )

    assert body.total_count == 1
    assert [str(item.id) for item in body.items] == [str(own.id)]
    assert body.items[0].slug.startswith("wireless-keyboard-")
    assert body.items[0].created_at == own.created_at
    assert body.items[0].skus_count == 1
    assert body.items[0].total_active_quantity == 7


def test_idor_query_param_seller_id_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    jwt_seller_id = uuid4()
    query_seller_id = uuid4()

    class FakeProductService:
        seen_seller_id = None

        def __init__(self, db: object) -> None:
            self.db = db

        async def list_for_seller_cabinet(self, **kwargs):
            self.__class__.seen_seller_id = kwargs["seller_id"]
            return {
                "items": [],
                "total_count": 0,
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
            }

    async def fake_current_seller():
        return SimpleNamespace(id=jwt_seller_id, is_active=True)

    async def fake_db():
        yield SimpleNamespace()

    monkeypatch.setattr(products_router, "ProductService", FakeProductService)
    app.dependency_overrides[products_router.get_current_seller] = fake_current_seller
    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).get(
            f"/api/v1/products?seller_id={query_seller_id}"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert FakeProductService.seen_seller_id == jwt_seller_id
    assert FakeProductService.seen_seller_id != query_seller_id


@pytest.mark.asyncio
async def test_deleted_products_visible_with_deleted_flag() -> None:
    seller_id = uuid4()
    active = _product(seller_id=seller_id, deleted=False)
    deleted = _product(seller_id=seller_id, deleted=True)
    FakeProductRepository.products = [active, deleted]

    without_deleted = await ProductService(SimpleNamespace()).list_for_seller_cabinet(
        seller_id=seller_id
    )
    with_deleted = await ProductService(SimpleNamespace()).list_for_seller_cabinet(
        seller_id=seller_id,
        include_deleted=True,
    )

    assert [item.deleted for item in without_deleted.items] == [False]
    assert sorted(item.deleted for item in with_deleted.items) == [False, True]


@pytest.mark.asyncio
async def test_status_filter_works_correctly() -> None:
    seller_id = uuid4()
    blocked = _product(seller_id=seller_id, status=ProductStatus.BLOCKED)
    moderated = _product(seller_id=seller_id, status=ProductStatus.MODERATED)
    FakeProductRepository.products = [blocked, moderated]

    body = await ProductService(SimpleNamespace()).list_for_seller_cabinet(
        seller_id=seller_id,
        status=ProductStatus.BLOCKED,
    )

    assert body.total_count == 1
    assert [item.status for item in body.items] == [ProductStatus.BLOCKED]
    assert [str(item.id) for item in body.items] == [str(blocked.id)]


@pytest.mark.asyncio
async def test_search_by_title_case_insensitive() -> None:
    seller_id = uuid4()
    matching = _product(seller_id=seller_id, title="Wireless Keyboard")
    hidden = _product(seller_id=seller_id, title="Office Mouse")
    FakeProductRepository.products = [matching, hidden]

    body = await ProductService(SimpleNamespace()).list_for_seller_cabinet(
        seller_id=seller_id,
        search="keyboard",
    )

    assert body.total_count == 1
    assert [str(item.id) for item in body.items] == [str(matching.id)]
