from uuid import UUID

from fastapi import HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.product import Product
from src.models.product import ProductStatus
from src.repositories.product_repo import ProductRepository
from src.schemas.product import PaginatedProducts, ProductCreate, ProductResponse, ProductUpdate


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ProductRepository(session)

    async def list_active(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
    ) -> PaginatedProducts:
        items, total = await self.repo.list_active(page, page_size, search)
        return PaginatedProducts(
            items=[ProductResponse.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_active(self, product_id: UUID) -> Product:
        product = await self.repo.get_with_skus(product_id)
        if not product or not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        return product

    async def get_for_seller(self, product_id: UUID, seller_id: UUID) -> dict[str, object]:
        product = await self.repo.get_with_skus(product_id)
        if not product or product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        return self._seller_product_detail(product)

    async def list_by_seller(self, seller_id: UUID) -> list[Product]:
        return await self.repo.list_by_seller(seller_id)

    def _seller_product_detail(self, product: Product) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "images": product.images,
            "characteristics": product.characteristics,
            "status": self._status_value(product.status),
            "category": product.category,
            "is_active": product.is_active,
            "deleted": product.deleted,
            "blocked": product.status
            in {ProductStatus.BLOCKED, ProductStatus.HARD_BLOCKED},
            "blocking_reason": product.blocking_reason,
            "field_reports": product.field_reports or [],
            "skus": [self._seller_sku_detail(sku) for sku in product.skus],
        }

    def _seller_sku_detail(self, sku: object) -> dict[str, object]:
        reserved_quantity = getattr(sku, "reserved_quantity", 0)
        stock = sku.stock
        return {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "name": sku.name,
            "price": sku.price,
            "cost_price": getattr(sku, "cost_price", None),
            "stock": stock,
            "active_quantity": max(stock - reserved_quantity, 0),
            "reserved_quantity": reserved_quantity,
            "images": sku.images,
            "is_active": sku.is_active,
        }

    def _status_value(self, product_status: object) -> str:
        if isinstance(product_status, ProductStatus):
            return product_status.value
        return str(product_status)

    async def create(self, seller_id: UUID, data: ProductCreate) -> Product:
        product = await self.repo.create_product(
            seller_id=seller_id,
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            images=data.images,
            characteristics=data.characteristics,
            category=data.category,
        )
        return await self.repo.get_with_skus(product.id)

    async def update(self, product_id: UUID, seller_id: UUID, data: ProductUpdate) -> Product:
        product = await self.repo.get_with_skus(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        if product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot edit hard-blocked product",
            )

        moderation_client = ModerationClient()
        json_before = moderation_client.product_snapshot(product)
        if data.title is not None:
            product.title = data.title
        if data.description is not None:
            product.description = data.description
        if data.category_id is not None:
            product.category_id = data.category_id
        if data.images is not None:
            product.images = data.images
        if data.characteristics is not None:
            product.characteristics = data.characteristics
        if data.category is not None:
            product.category = data.category
        if data.is_active is not None:
            product.is_active = data.is_active
        should_send_to_moderation = product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        if should_send_to_moderation:
            product.status = ProductStatus.ON_MODERATION
        await self.repo.session.flush()
        if should_send_to_moderation:
            await moderation_client.send_product_edited(
                product,
                json_before=json_before,
            )
        return await self.repo.get_with_skus(product.id)

    async def delete(self, product_id: UUID, seller_id: UUID) -> None:
        product = await self.repo.get_with_skus(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        if product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        if product.deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product already deleted",
            )

        product.deleted = True
        product.is_active = False
        await self.repo.session.flush()
        try:
            await ModerationClient().send_product_deleted(product)
        except httpx.HTTPError:
            pass
        try:
            await B2CClient().send_product_deleted(product)
        except httpx.HTTPError:
            pass
