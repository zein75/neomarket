from uuid import UUID

from fastapi import HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.product import ProductStatus
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

    async def get_public_sku(self, sku_id: UUID) -> dict[str, object]:
        sku = await self.sku_repo.get_with_product(sku_id)
        product = getattr(sku, "product", None) if sku else None
        if not sku or not product or not self._is_publicly_visible(product, sku):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SKU_NOT_FOUND",
                    "message": "SKU not found",
                },
            )
        return {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "name": sku.name,
            "price": sku.price,
            "discount": getattr(sku, "discount", 0),
            "article": getattr(sku, "article", None),
            "characteristics": getattr(sku, "characteristics", {}),
            "stock_quantity": sku.stock,
            "active_quantity": self._active_quantity(sku),
            "images": sku.images,
            "is_active": sku.is_active,
        }

    async def create(self, seller_id: UUID, data: SKUCreate) -> SKU:
        product = await self.product_repo.get_seller_product_for_update(
            data.product_id,
            seller_id,
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SKU_HARD_BLOCKED_PRODUCT",
                    "message": "Cannot add SKU to hard-blocked product",
                },
            )

        is_first_sku = len(product.skus) == 0
        should_send_edited = product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        moderation_client = ModerationClient()
        json_before = (
            moderation_client.product_snapshot(product) if should_send_edited else None
        )
        sku = await self.sku_repo.create_sku(
            product_id=data.product_id,
            name=data.name,
            price=data.price,
            stock=data.stock,
            images=[image.url for image in data.images],
        )
        if all(existing.id != sku.id for existing in product.skus):
            product.skus.append(sku)
        if is_first_sku or should_send_edited:
            product.status = ProductStatus.ON_MODERATION
            await self.sku_repo.session.flush()
        if is_first_sku:
            await moderation_client.send_product_created(product)
        elif should_send_edited and json_before is not None:
            await moderation_client.send_product_edited(
                product,
                json_before=json_before,
            )
        return sku

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
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot edit SKU of hard-blocked product",
            )

        moderation_client = ModerationClient()
        json_before = moderation_client.product_snapshot(product)
        if data.name is not None:
            sku.name = data.name
        if data.price is not None:
            sku.price = data.price
        if data.stock is not None:
            sku.stock = data.stock
        if data.images is not None:
            sku.images = [image.url for image in data.images]
        if data.is_active is not None:
            sku.is_active = data.is_active
        should_send_to_moderation = product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        if should_send_to_moderation:
            product.status = ProductStatus.ON_MODERATION
        await self.sku_repo.session.flush()
        await self.sku_repo.session.refresh(sku)
        if should_send_to_moderation:
            await moderation_client.send_product_edited(
                product,
                json_before=json_before,
            )
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
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SKU_HARD_BLOCKED_PRODUCT",
                    "message": "Cannot delete SKU of hard-blocked product",
                },
            )
        if getattr(sku, "reserved_quantity", 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SKU_ACTIVE_RESERVES",
                    "message": "Cannot delete SKU with active reserves",
                },
            )

        was_visible_in_b2c = (
            product.status == ProductStatus.MODERATED and self._active_quantity(sku) > 0
        )
        if sku in product.skus:
            product.skus.remove(sku)
        is_last_sku_deleted = len(product.skus) == 0
        await self.sku_repo.delete(sku)

        if is_last_sku_deleted and product.status == ProductStatus.ON_MODERATION:
            product.status = ProductStatus.CREATED
            await self.sku_repo.session.flush()
            try:
                await ModerationClient().send_product_deleted(product)
            except httpx.HTTPError:
                pass

        if was_visible_in_b2c:
            try:
                await B2CClient().send_sku_out_of_stock(sku)
            except httpx.HTTPError:
                pass

    def _active_quantity(self, sku: object) -> int:
        return max(sku.stock - getattr(sku, "reserved_quantity", 0), 0)

    def _is_publicly_visible(self, product: object, sku: object) -> bool:
        if str(product.status) != ProductStatus.MODERATED.value:
            return False
        if getattr(product, "deleted", False):
            return False
        if not getattr(sku, "is_active", False):
            return False
        return self._active_quantity(sku) > 0
