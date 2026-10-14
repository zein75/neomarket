import base64
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    get_current_seller,
    get_db,
    get_seller_or_service,
    verify_service_key,
)
from src.models.seller import Seller
from src.models.product import ProductStatus
from src.schemas.product import (
    ProductCreate,
    ProductDetailResponse,
    ProductPatch,
    ProductPublicBatchRequest,
    ProductPaginatedResponse,
    ProductPublicPaginatedResponse,
    ProductPublicResponse,
    ProductResponse,
    ProductUpdate,
)
from src.services.product_service import ProductService

router = APIRouter(tags=["products"])


def _decode_cursor(cursor: str | None) -> int:
    if not isinstance(cursor, str) or not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURSOR", "message": "Invalid product cursor"},
        ) from exc
    if offset < 0 or offset > 10_000:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURSOR", "message": "Invalid product cursor"},
        )
    return offset


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _parse_ids(ids: str | None) -> list[UUID] | None:
    if not ids:
        return None
    return [UUID(raw_id.strip()) for raw_id in ids.split(",") if raw_id.strip()]


@router.get("/api/v1/seller/products")
async def list_seller_products_cursor(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    offset = _decode_cursor(cursor)
    result = await ProductService(db).list_for_seller_cabinet(
        seller_id=current_seller.id,
        limit=limit,
        offset=offset,
    )
    total = int(result.total_count)
    next_offset = offset + limit
    has_more = next_offset < total
    return {
        "items": result.items,
        "page": {
            "has_more": has_more,
            "next_cursor": _encode_cursor(next_offset) if has_more else None,
        },
    }


@router.get("/products", response_model=ProductPublicPaginatedResponse)
async def list_products(
    category_id: UUID | None = Query(None),
    search: str | None = Query(None),
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    seller_id: UUID | None = Query(None),
    in_stock: bool | None = Query(None),
    sort: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.list_public_catalog(
        category_id=category_id,
        search=search,
        min_price=min_price,
        max_price=max_price,
        seller_id=seller_id,
        in_stock=in_stock,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductPublicResponse)
async def get_product(
    product_id: UUID,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.get_public_detail(product_id)


@router.get(
    "/api/v1/public/products/{product_id}/similar",
    response_model=ProductPublicPaginatedResponse,
)
async def get_similar_public_products(
    product_id: UUID,
    category: UUID = Query(...),
    limit: int = Query(8, ge=1, le=20),
    offset: int = Query(0, ge=0, le=10_000),
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.list_similar_public(
        product_id,
        category_id=category,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/products",
    response_model=ProductPaginatedResponse | ProductPublicPaginatedResponse,
)
async def list_seller_products(
    ids: str | None = Query(None),
    category: UUID | None = Query(None),
    category_id: UUID | None = Query(None),
    search: str | None = Query(None),
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    seller_id: UUID | None = Query(None),
    in_stock: bool | None = Query(None),
    sort: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    status: ProductStatus | None = Query(None),
    include_deleted: bool = Query(False),
    deleted: bool | None = Query(None),
    current_seller: Seller | None = Depends(get_seller_or_service),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    if current_seller is None:
        return await svc.list_public_catalog(
            product_ids=_parse_ids(ids),
            category_id=category or category_id,
            search=search,
            min_price=min_price,
            max_price=max_price,
            seller_id=seller_id,
            in_stock=in_stock,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    return await svc.list_for_seller_cabinet(
        seller_id=current_seller.id,
        limit=limit,
        offset=offset,
        status=status,
        include_deleted=include_deleted or deleted is True,
        search=search,
    )


@router.get(
    "/api/v1/public/products",
    response_model=ProductPublicPaginatedResponse,
)
async def list_public_products(
    ids: str | None = Query(None),
    category_id: UUID | None = Query(None),
    search: str | None = Query(None),
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    seller_id: UUID | None = Query(None),
    in_stock: bool | None = Query(None),
    sort: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.list_public_catalog(
        product_ids=_parse_ids(ids),
        category_id=category_id,
        search=search,
        min_price=min_price,
        max_price=max_price,
        seller_id=seller_id,
        in_stock=in_stock,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/api/v1/public/products/batch",
    response_model=list[ProductPublicResponse],
)
async def get_public_products_batch(
    data: ProductPublicBatchRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.get_public_batch(data.product_ids)


@router.get(
    "/api/v1/public/products/{product_id}",
    response_model=ProductPublicResponse,
)
async def get_public_product(
    product_id: UUID,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.get_public_detail(product_id)


@router.post("/api/v1/seller/products", response_model=ProductResponse, status_code=201)
@router.post("/api/v1/products", response_model=ProductResponse, status_code=201, include_in_schema=False)
async def create_product(
    data: ProductCreate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    product = await svc.create(current_seller.id, data)
    await db.commit()
    return product


@router.get(
    "/api/v1/seller/products/{product_id}",
    response_model=ProductDetailResponse | ProductPublicResponse,
)
@router.get(
    "/api/v1/products/{product_id}",
    response_model=ProductDetailResponse | ProductPublicResponse,
)
async def get_seller_product(
    product_id: UUID,
    current_seller: Seller | None = Depends(get_seller_or_service),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    if current_seller is None:
        return await svc.get_service_detail(product_id)
    return await svc.get_for_seller(product_id, current_seller.id)


@router.get("/api/v1/seller/products/{product_id}/moderation-status")
async def get_moderation_status(
    product_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    product = await ProductService(db).get_for_seller(product_id, current_seller.id)
    product_status = (
        product.get("status") if isinstance(product, dict) else getattr(product, "status", None)
    )
    return {"product_id": str(product_id), "status": product_status}


@router.put("/api/v1/seller/products/{product_id}", response_model=ProductResponse)
@router.put("/api/v1/products/{product_id}", response_model=ProductResponse, include_in_schema=False)
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    product = await svc.update(product_id, current_seller.id, data)
    await db.commit()
    return product


@router.patch("/api/v1/products/{product_id}", response_model=ProductResponse)
async def patch_product(
    product_id: UUID,
    data: ProductUpdate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await update_product(product_id, data, current_seller, db)


@router.patch("/api/v1/seller/products/{product_id}", response_model=ProductResponse)
async def patch_seller_product(
    product_id: UUID,
    data: ProductPatch,
    if_match: str = Header(..., alias="If-Match"),
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Canonical optimistic-concurrency product update."""
    if not if_match.strip():
        raise HTTPException(
            status_code=409,
            detail={"code": "REVISION_REQUIRED", "message": "If-Match is required"},
        )
    current = await ProductService(db).get_for_seller(product_id, current_seller.id)
    current_updated_at = current.get("updated_at") if isinstance(current, dict) else None
    if if_match != "*" and current_updated_at is not None and if_match.strip('"') != str(current_updated_at):
        raise HTTPException(
            status_code=409,
            detail={"code": "REVISION_CONFLICT", "message": "Product revision is stale"},
        )
    return await update_product(product_id, data, current_seller, db)


@router.delete("/api/v1/products/{product_id}", status_code=204, include_in_schema=False)
async def delete_product(
    product_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = ProductService(db)
    await svc.delete(product_id, current_seller.id)
    await db.commit()


@router.delete("/api/v1/seller/products/{product_id}", status_code=202)
async def delete_seller_product(
    product_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ProductService(db).delete(product_id, current_seller.id)
    await db.commit()
