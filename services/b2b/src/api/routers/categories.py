from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db, verify_service_key
from src.models.seller import Seller
from src.schemas.category import CategoryDetailResponse, CategoryListResponse
from src.services.category_service import CategoryService

router = APIRouter(tags=["categories"])


@router.get("/api/v1/seller/categories", response_model=CategoryListResponse)
async def list_seller_categories(
    _: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return active categories to authenticated sellers creating products."""
    return await CategoryService(db).list_active()


@router.get("/api/v1/public/categories", response_model=CategoryListResponse)
async def list_public_categories(
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await CategoryService(db).list_active()


@router.get("/api/v1/public/categories/{category_id}", response_model=CategoryDetailResponse)
async def get_public_category(
    category_id: UUID,
    include_product_count: bool = Query(False),
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await CategoryService(db).get_detail(
        category_id,
        include_product_count=include_product_count,
    )
