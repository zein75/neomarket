from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db
from src.models.seller import Seller
from src.schemas.sku import SKUCreate, SKUResponse, SKUUpdate
from src.services.sku_service import SKUService

router = APIRouter(tags=["skus"])


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


@router.patch("/api/v1/skus/{sku_id}", response_model=SKUResponse)
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


@router.delete("/api/v1/skus/{sku_id}", status_code=204)
async def delete_sku(
    sku_id: UUID,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = SKUService(db)
    await svc.delete(sku_id, current_seller.id)
    await db.commit()
