from typing import Any

from fastapi import APIRouter, Query

from src.clients.b2b_client import B2BClient
from src.core.config import settings

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
) -> Any:
    async with B2BClient(settings.b2b_base_url) as client:
        return await client.get_products(page=page, page_size=page_size, search=search)


@router.get("/products/{product_id}")
async def get_product(product_id: str) -> Any:
    async with B2BClient(settings.b2b_base_url) as client:
        return await client.get_product(product_id)
