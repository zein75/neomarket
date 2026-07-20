from fastapi import APIRouter, Query

from src.services.catalog_service import CatalogService

router = APIRouter(tags=["catalog"])


@router.get("/api/v1/catalog/products")
# Hidden aliases are kept for legacy storefront clients while the canonical path
# remains /api/v1/catalog/products.
@router.get("/api/v1/products", include_in_schema=False)
@router.get("/catalog/products", include_in_schema=False)
async def list_products(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    search: str | None = Query(None, max_length=200),
    sort: str = Query("popularity"),
    seller_id: str | None = Query(None),
    category_id: str | None = Query(None, alias="filter[category_id]"),
    price_min: int | None = Query(None, ge=0, alias="filter[price_min]"),
    price_max: int | None = Query(None, ge=0, alias="filter[price_max]"),
    in_stock: bool | None = Query(None, alias="filter[in_stock]"),
) -> dict[str, object]:
    if page is not None:
        limit = page_size or limit
        offset = (page - 1) * limit
    return await CatalogService().list_products(
        category_id=category_id,
        price_min=price_min,
        price_max=price_max,
        in_stock=in_stock,
        q=q or search,
        sort=sort,
        limit=limit,
        offset=offset,
        seller_id=seller_id,
    )


# Non-spec extension used by the storefront filter UI. The response contract
# should be added to the shared OpenAPI spec before exposing it to new clients.
@router.get("/api/v1/catalog/facets")
async def get_facets() -> dict[str, object]:
    return await CatalogService().facets()


@router.get("/api/v1/catalog/products/{product_id}")
@router.get("/api/v1/products/{product_id}", include_in_schema=False)
@router.get("/catalog/products/{product_id}", include_in_schema=False)
async def get_product(product_id: str) -> dict[str, object]:
    return await CatalogService().get_product_card(product_id)
