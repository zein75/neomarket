from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db, verify_service_key
from src.models.seller import Seller
from src.schemas.product import SKUPublicResponse
from src.schemas.sku import SKUPatch, SKUCreate, SKUResponse, SKUUpdate, StockAdjustmentRequest
from src.services.sku_service import SKUService

router = APIRouter(tags=["skus"])


@router.post("/api/v1/seller/skus/{sku_id}/stock-adjustments", response_model=SKUResponse)
async def adjust_stock(
    sku_id: UUID,
    data: StockAdjustmentRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> SKUResponse:
    sku = await SKUService(db).adjust_stock(
        sku_id, current_seller.id, data, str(idempotency_key)
    )
    await db.commit()
    await db.refresh(sku)
    return SKUResponse.model_validate(sku)


@router.get("/api/v1/public/skus/{sku_id}", response_model=SKUPublicResponse)
async def get_public_sku(
    sku_id: UUID,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SKUService(db)
    return await svc.get_public_sku(sku_id)


@router.get("/api/v1/seller/skus/{sku_id}", response_model=SKUResponse)
async def get_seller_sku(
    sku_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> SKUResponse:
    sku = await SKUService(db).get_for_seller(sku_id, current_seller.id)
    return SKUResponse.model_validate(sku)


@router.get("/api/v1/products/{product_id}/skus", response_model=list[SKUResponse])
async def list_skus(
    product_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SKUService(db)
    return await svc.list_by_product(product_id, current_seller.id)


@router.post("/api/v1/skus", response_model=SKUResponse, status_code=201)
async def create_sku(
    data: SKUCreate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SKUService(db)
    sku = await svc.create(current_seller.id, data)
    await db.commit()
    await db.refresh(sku)
    return sku


@router.post(
    "/api/v1/seller/products/{product_id}/skus",
    response_model=SKUResponse,
    status_code=201,
)
@router.post(
    "/seller/products/{product_id}/skus",
    response_model=SKUResponse,
    status_code=201,
    include_in_schema=False,
)
async def create_sku_legacy(
    product_id: UUID,
    data: SKUCreate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    data.product_id = product_id
    return await create_sku(data, current_seller, db)


@router.put("/api/v1/seller/skus/{sku_id}", response_model=SKUResponse)
@router.put("/api/v1/skus/{sku_id}", response_model=SKUResponse, include_in_schema=False)
async def update_sku(
    sku_id: UUID,
    data: SKUUpdate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SKUService(db)
    sku = await svc.update(sku_id, current_seller.id, data)
    await db.commit()
    await db.refresh(sku)
    return sku


@router.patch("/api/v1/skus/{sku_id}", response_model=SKUResponse, include_in_schema=False)
async def patch_sku(
    sku_id: UUID,
    data: SKUUpdate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await update_sku(sku_id, data, current_seller, db)


@router.patch("/api/v1/seller/skus/{sku_id}", response_model=SKUResponse)
async def patch_seller_sku(
    sku_id: UUID,
    data: SKUPatch,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await update_sku(sku_id, data, current_seller, db)


@router.delete("/api/v1/seller/skus/{sku_id}", status_code=204)
@router.delete("/api/v1/skus/{sku_id}", status_code=204, include_in_schema=False)
async def delete_sku(
    sku_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = SKUService(db)
    await svc.delete(sku_id, current_seller.id)
    await db.commit()
