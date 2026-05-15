from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db
from src.models.seller import Seller
from src.schemas.product import PaginatedProducts, ProductCreate, ProductResponse
from src.services.product_service import ProductService

router = APIRouter(tags=["products"])


# --- Public catalog (called by B2C) ---

@router.get("/products", response_model=PaginatedProducts)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.list_active(page=page, page_size=page_size, search=search)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    return await svc.get_active(product_id)


@router.post("/api/v1/products", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ProductService(db)
    product = await svc.create(current_seller.id, data)
    await db.commit()
    return product
