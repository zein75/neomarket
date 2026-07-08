from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sku import SKU
from src.repositories.product_repo import ProductRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.sku import SKUCreate, SKUUpdate


class SKUService:
    def __init__(self, session: AsyncSession) -> None:
        self.sku_repo = SKURepository(session)
        self.product_repo = ProductRepository(session)

    async def list_by_product(self, product_id: UUID, seller_id: UUID) -> list[SKU]:
        product = await self.product_repo.get_seller_product(product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        return await self.sku_repo.list_by_product(product_id)

    async def create(self, product_id: UUID, seller_id: UUID, data: SKUCreate) -> SKU:
        product = await self.product_repo.get_seller_product(product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        return await self.sku_repo.create(
            product_id=product_id,
            name=data.name,
            price=data.price,
            stock=data.stock,
        )

    async def update(self, sku_id: UUID, seller_id: UUID, data: SKUUpdate) -> SKU:
        sku = await self.sku_repo.get_by_id(sku_id)
        if not sku:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found"
            )
        product = await self.product_repo.get_seller_product(sku.product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        if data.name is not None:
            sku.name = data.name
        if data.price is not None:
            sku.price = data.price
        if data.stock is not None:
            sku.stock = data.stock
        if data.is_active is not None:
            sku.is_active = data.is_active
        await self.sku_repo.session.flush()
        await self.sku_repo.session.refresh(sku)
        return sku

    async def delete(self, sku_id: UUID, seller_id: UUID) -> None:
        sku = await self.sku_repo.get_by_id(sku_id)
        if not sku:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found"
            )
        product = await self.product_repo.get_seller_product(sku.product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        await self.sku_repo.delete(sku)
