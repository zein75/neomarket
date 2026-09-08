from datetime import datetime, timezone
from random import sample
from uuid import UUID

from fastapi import HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.product import Product
from src.models.product import ProductStatus
from src.repositories.product_repo import ProductRepository
from src.schemas.product import (
    PaginatedProducts,
    ProductCreate,
    ProductPaginatedResponse,
    ProductPublicPaginatedResponse,
    ProductResponse,
    ProductUpdate,
)


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
        if not product or not self._is_publicly_visible(product):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found",
                },
            )
        return product

    async def get_public_detail(self, product_id: UUID) -> dict[str, object]:
        product = await self.get_active(product_id)
        return self._public_product_detail(product)

    async def get_service_detail(self, product_id: UUID) -> dict[str, object]:
        product = await self.repo.get_with_skus(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found",
                },
            )
        return self._public_product_detail(product)

    async def get_public_batch(self, product_ids: list[UUID]) -> list[dict[str, object]]:
        products = await self.repo.list_public_catalog(product_ids)
        visible_by_id = {
            product.id: product
            for product in products
            if self._is_publicly_visible(product)
        }
        return [
            self._public_product_detail(visible_by_id[product_id])
            for product_id in product_ids
            if product_id in visible_by_id
        ]

    async def get_for_seller(self, product_id: UUID, seller_id: UUID) -> dict[str, object]:
        product = await self.repo.get_with_skus(product_id)
        if not product or product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found",
                },
            )
        return self._seller_product_detail(product)

    async def list_public_catalog(
        self,
        product_ids: list[UUID] | None = None,
        *,
        category_id: UUID | None = None,
        search: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        seller_id: UUID | None = None,
        in_stock: bool | None = None,
        sort: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ProductPublicPaginatedResponse:
        products = await self.repo.list_public_catalog(product_ids)
        filtered = [
            product
            for product in products
            if self._is_publicly_visible(product)
            and self._matches_public_catalog(
                product,
                category_id=category_id,
                search=search,
                min_price=min_price,
                max_price=max_price,
                seller_id=seller_id,
                in_stock=in_stock,
            )
        ]
        sorted_products = self._sort_public_catalog(filtered, sort)
        page = sorted_products[offset : offset + limit]
        return ProductPublicPaginatedResponse(
            items=[self._public_product_detail(product) for product in page],
            total_count=len(filtered),
            limit=limit,
            offset=offset,
        )

    async def list_similar_public(
        self,
        product_id: UUID,
        *,
        category_id: UUID,
        limit: int = 8,
        offset: int = 0,
    ) -> ProductPublicPaginatedResponse:
        if not await self.repo.category_exists(category_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Nonexistent category id",
                },
            )
        current = await self.repo.get_with_skus(product_id)
        if not current or not self._is_publicly_visible(current):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NOT_FOUND",
                    "message": "Product not found",
                },
            )

        products = await self.repo.list_public_catalog()
        same_category = [
            product
            for product in products
            if product.id != product_id
            and self._is_publicly_visible(product)
            and product.category_id == category_id
        ]
        same_category = sample(same_category, k=len(same_category))
        candidates = same_category
        if len(candidates) < offset + limit:
            parent_id = await self.repo.get_category_parent_id(category_id)
            if parent_id is not None:
                sibling_category_ids = set(
                    await self.repo.list_category_ids_by_parent(parent_id)
                )
                fallback = [
                    product
                    for product in products
                    if product.id != product_id
                    and product.category_id != category_id
                    and product.category_id in sibling_category_ids
                    and self._is_publicly_visible(product)
                ]
                fallback = sample(fallback, k=len(fallback))
                candidates = [*candidates, *fallback]
        page = candidates[offset : offset + limit]
        return ProductPublicPaginatedResponse(
            items=[self._public_product_detail(product) for product in page],
            total_count=len(candidates),
            limit=limit,
            offset=offset,
        )

    async def list_by_seller(self, seller_id: UUID) -> list[Product]:
        return await self.repo.list_by_seller(seller_id)

    async def list_for_seller_cabinet(
        self,
        *,
        seller_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: ProductStatus | None = None,
        include_deleted: bool = False,
        search: str | None = None,
    ) -> ProductPaginatedResponse:
        rows, total = await self.repo.list_for_seller_cabinet(
            seller_id=seller_id,
            limit=limit,
            offset=offset,
            status=self._status_value(status) if status else None,
            include_deleted=include_deleted,
            search=search,
        )
        return ProductPaginatedResponse(
            items=[
                self._seller_product_list_item(
                    product,
                    skus_count=skus_count,
                    total_active_quantity=total_active_quantity,
                )
                for product, skus_count, total_active_quantity in rows
            ],
            total_count=total,
            limit=limit,
            offset=offset,
        )

    def _seller_product_list_item(
        self,
        product: Product,
        *,
        skus_count: int,
        total_active_quantity: int,
    ) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "slug": self._product_slug(product),
            "images": ProductResponse._normalize_images(product.images, product.id),
            "characteristics": ProductResponse._normalize_characteristics(
                product.characteristics
            ),
            "status": self._status_value(product.status),
            "category": product.category,
            "is_active": product.is_active,
            "deleted": product.deleted,
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
            "skus_count": skus_count,
            "total_active_quantity": total_active_quantity,
        }

    def _seller_product_detail(self, product: Product) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "slug": self._product_slug(product),
            "images": ProductResponse._normalize_images(product.images, product.id),
            "characteristics": ProductResponse._normalize_characteristics(
                product.characteristics
            ),
            "status": self._status_value(product.status),
            "blocking_reason_id": ProductResponse._blocking_reason_id(
                {"blocking_reason": getattr(product, "blocking_reason", None)}
            ),
            "moderator_comment": ProductResponse._moderator_comment(
                {
                    "blocking_reason": getattr(product, "blocking_reason", None),
                    "field_reports": getattr(product, "field_reports", []),
                }
            ),
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(product, "updated_at", datetime.now(timezone.utc)),
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
            "created_at": getattr(sku, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(sku, "updated_at", datetime.now(timezone.utc)),
        }

    def _is_publicly_visible(self, product: Product) -> bool:
        if str(product.status) != ProductStatus.MODERATED.value:
            return False
        if product.deleted:
            return False
        return any(self._active_quantity(sku) > 0 for sku in product.skus)

    def _public_product_short(self, product: Product) -> dict[str, object]:
        images = ProductResponse._normalize_images(product.images, product.id)
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "slug": self._product_slug(product),
            "images": images,
            "image": images[0]["url"] if images else "",
            "characteristics": ProductResponse._normalize_characteristics(
                product.characteristics
            ),
            "status": self._status_value(product.status),
            "price": self._min_public_price(product),
            "in_stock": True,
            "is_in_cart": False,
            "min_price": self._min_public_price(product),
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
        }

    def _public_product_detail(self, product: Product) -> dict[str, object]:
        images = ProductResponse._normalize_images(product.images, product.id)
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category_id": str(product.category_id) if product.category_id else None,
            "slug": self._product_slug(product),
            "images": images,
            "image": images[0]["url"] if images else "",
            "price": self._min_public_price(product),
            "in_stock": True,
            "is_in_cart": False,
            "characteristics": ProductResponse._normalize_characteristics(
                product.characteristics
            ),
            "status": self._status_value(product.status),
            "blocking_reason_id": ProductResponse._blocking_reason_id(
                {"blocking_reason": getattr(product, "blocking_reason", None)}
            ),
            "moderator_comment": ProductResponse._moderator_comment(
                {
                    "blocking_reason": getattr(product, "blocking_reason", None),
                    "field_reports": getattr(product, "field_reports", []),
                }
            ),
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(product, "updated_at", datetime.now(timezone.utc)),
            "skus": [
                self._public_sku_detail(sku)
                for sku in product.skus
                if self._active_quantity(sku) > 0
            ],
        }

    def _public_sku_detail(self, sku: object) -> dict[str, object]:
        return {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "name": sku.name,
            "price": sku.price,
            "discount": getattr(sku, "discount", 0),
            "article": getattr(sku, "article", None),
            "characteristics": ProductResponse._normalize_characteristics(
                getattr(sku, "characteristics", [])
            ),
            "stock_quantity": sku.stock,
            "active_quantity": self._active_quantity(sku),
            "images": sku.images,
            "is_active": sku.is_active,
            "created_at": getattr(sku, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(sku, "updated_at", datetime.now(timezone.utc)),
        }

    def _matches_public_catalog(
        self,
        product: Product,
        *,
        category_id: UUID | None,
        search: str | None,
        min_price: int | None,
        max_price: int | None,
        seller_id: UUID | None,
        in_stock: bool | None,
    ) -> bool:
        public_min_price = self._min_public_price(product)
        if category_id and product.category_id != category_id:
            return False
        if seller_id and product.seller_id != seller_id:
            return False
        if min_price is not None and (
            public_min_price is None or public_min_price < min_price
        ):
            return False
        if max_price is not None and (
            public_min_price is None or public_min_price > max_price
        ):
            return False
        if in_stock is True and not any(
            self._active_quantity(sku) > 0 for sku in product.skus
        ):
            return False
        if search:
            haystack = " ".join(
                value
                for value in (product.title, product.description)
                if value
            ).lower()
            if search.lower() not in haystack:
                return False
        return True

    def _sort_public_catalog(
        self,
        products: list[Product],
        sort: str | None,
    ) -> list[Product]:
        if sort == "price_asc":
            return sorted(products, key=lambda product: self._min_public_price(product) or 0)
        if sort == "price_desc":
            return sorted(
                products,
                key=lambda product: self._min_public_price(product) or 0,
                reverse=True,
            )
        if sort == "new":
            return sorted(
                products,
                key=lambda product: getattr(
                    product,
                    "created_at",
                    datetime.now(timezone.utc),
                ),
                reverse=True,
            )
        return products

    def _min_public_price(self, product: Product) -> int | None:
        prices = [
            sku.price
            for sku in product.skus
            if self._active_quantity(sku) > 0 and sku.price is not None
        ]
        return min(prices) if prices else None

    def _product_slug(self, product: Product) -> str:
        return getattr(product, "slug", None) or ProductResponse._slug(
            product.title, product.id
        )

    def _active_quantity(self, sku: object) -> int:
        return max(sku.stock - getattr(sku, "reserved_quantity", 0), 0)

    def _status_value(self, product_status: object) -> str:
        if isinstance(product_status, ProductStatus):
            return product_status.value
        return str(product_status)

    async def create(self, seller_id: UUID, data: ProductCreate) -> Product:
        await self._ensure_category_exists(data.category_id)
        product = await self.repo.create_product(
            seller_id=seller_id,
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            images=[image.url for image in data.images],
            characteristics={
                characteristic.name: characteristic.value
                for characteristic in data.characteristics
            },
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
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PRODUCT_ACCESS_DENIED",
                    "message": "Access denied",
                },
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PRODUCT_HARD_BLOCKED",
                    "message": "Cannot edit hard-blocked product",
                },
            )

        moderation_client = ModerationClient()
        json_before = moderation_client.product_snapshot(product)
        if data.title is not None:
            product.title = data.title
        if data.description is not None:
            product.description = data.description
        if data.category_id is not None:
            await self._ensure_category_exists(data.category_id)
            product.category_id = data.category_id
        if data.images is not None:
            product.images = [image.url for image in data.images]
        if data.characteristics is not None:
            product.characteristics = {
                characteristic.name: characteristic.value
                for characteristic in data.characteristics
            }
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

    async def _ensure_category_exists(self, category_id: UUID) -> None:
        if not await self.repo.category_exists(category_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Category not found",
                },
            )

    async def delete(self, product_id: UUID, seller_id: UUID) -> None:
        product = await self.repo.get_with_skus(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        if product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PRODUCT_ACCESS_DENIED",
                    "message": "Access denied",
                },
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PRODUCT_HARD_BLOCKED",
                    "message": "Cannot delete hard-blocked product",
                },
            )
        if product.deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Product already deleted",
                },
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
