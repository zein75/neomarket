from datetime import datetime, timezone
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from random import sample
from uuid import UUID, uuid4

from fastapi import HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.category import Category
from src.models.brand import Brand
from src.models.attribute_definition import AttributeDefinition
from src.models.product import Product
from src.models.product import ProductStatus
from src.models.product_version import ProductVersion
from src.models.seller_product_creation import SellerProductCreation
from src.models.seller_media_asset import SellerMediaAsset
from src.models.sku import SKU
from src.repositories.product_repo import ProductRepository
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.schemas.product import (
    DraftVariantInput,
    PaginatedProducts,
    ProductCreate,
    ProductDraftCreate,
    ProductDraftResponse,
    ProductPaginatedResponse,
    ProductPublicPaginatedResponse,
    ProductResponse,
    ProductUpdate,
    ProductWithFirstSKUCreate,
)
from src.schemas.sku import SKUCreate
from src.services.sku_service import SKUService


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ProductRepository(session)

    async def _pii_attribute_codes(self) -> set[str]:
        scalars = getattr(self.repo.session, "scalars", None)
        if not callable(scalars):
            # Test/compatibility repositories can omit the taxonomy read model;
            # production SQLAlchemy sessions always expose this query method.
            return set()
        return set((await scalars(
            select(AttributeDefinition.code).where(
                AttributeDefinition.pii.is_(True),
                AttributeDefinition.status == "ACTIVE",
            )
        )).all())

    @staticmethod
    def _without_pii(values: object, pii_codes: set[str]) -> object:
        if isinstance(values, dict):
            return {key: value for key, value in values.items() if key not in pii_codes}
        return values

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
        return self._public_product_detail(product, pii_codes=await self._pii_attribute_codes())

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
        return self._public_product_detail(product, include_unavailable_skus=True, pii_codes=await self._pii_attribute_codes())

    async def get_public_batch(
        self,
        product_ids: list[UUID],
        *,
        include_unavailable: bool = False,
    ) -> list[dict[str, object]]:
        products = (
            await self.repo.list_cart_products(product_ids)
            if include_unavailable
            else await self.repo.list_public_catalog(product_ids)
        )
        visible_by_id = {
            product.id: product
            for product in products
            if include_unavailable or self._is_publicly_visible(product)
        }
        pii_codes = await self._pii_attribute_codes()
        return [
            self._public_product_detail(
                visible_by_id[product_id],
                include_unavailable_skus=include_unavailable,
                pii_codes=pii_codes,
            )
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
        page_loader = getattr(self.repo, "list_public_catalog_page", None)
        if callable(page_loader):
            products, total_count = await page_loader(
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
            pii_codes = await self._pii_attribute_codes()
            return ProductPublicPaginatedResponse(
                items=[self._public_product_detail(product, pii_codes=pii_codes) for product in products],
                total_count=total_count,
                limit=limit,
                offset=offset,
            )
        try:
            products = await self.repo.list_public_catalog(
                product_ids,
                category_id=category_id,
                search=search,
                min_price=min_price,
                max_price=max_price,
                seller_id=seller_id,
                in_stock=in_stock,
                sort=sort,
            )
        except TypeError:
            # Lightweight repositories used by unit tests may expose the old
            # positional-only adapter; production SQLAlchemy repositories use
            # the filtered query above.
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
        pii_codes = await self._pii_attribute_codes()
        return ProductPublicPaginatedResponse(
            items=[self._public_product_detail(product, pii_codes=pii_codes) for product in page],
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
        pii_codes = await self._pii_attribute_codes()
        return ProductPublicPaginatedResponse(
            items=[self._public_product_detail(product, pii_codes=pii_codes) for product in page],
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
        include_skus: bool = False,
    ) -> ProductPaginatedResponse:
        repo_kwargs = dict(
            seller_id=seller_id,
            limit=limit,
            offset=offset,
            status=self._status_value(status) if status else None,
            include_deleted=include_deleted,
            search=search,
        )
        if include_skus:
            repo_kwargs["include_skus"] = True
        rows, total = await self.repo.list_for_seller_cabinet(**repo_kwargs)
        return ProductPaginatedResponse(
            items=[
                self._seller_product_list_item(
                    product,
                    skus_count=skus_count,
                    total_active_quantity=total_active_quantity,
                    include_skus=include_skus,
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
        include_skus: bool = False,
    ) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "category_id": str(product.category_id) if product.category_id else None,
            "brand_id": str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None,
            "slug": self._product_slug(product),
            "images": ProductResponse._normalize_images(product.images, product.id),
            "characteristics": ProductResponse._normalize_characteristics(
                product.characteristics
            ),
            "status": self._status_value(product.status),
            "is_active": product.is_active,
            "deleted": product.deleted,
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(product, "updated_at", datetime.now(timezone.utc)),
            "skus_count": skus_count,
            "total_active_quantity": total_active_quantity,
            "skus": [self._seller_sku_detail(sku) for sku in product.skus] if include_skus else None,
        }

    def _seller_product_detail(self, product: Product) -> dict[str, object]:
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "category_id": str(product.category_id) if product.category_id else None,
            "brand_id": str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None,
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
            "revision": int(getattr(product, "revision", 1)),
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
            "price_minor": sku.price,
            "currency": getattr(sku, "currency", "RUB"),
            "article": getattr(sku, "seller_article", None),
            "seller_article": getattr(sku, "seller_article", None),
            "options": getattr(sku, "options", {}),
            "characteristics": getattr(sku, "options", {}),
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
        status_value = str(product.status)
        currently_moderated = status_value == ProductStatus.MODERATED.value
        has_prior_publication = (
            getattr(product, "published_revision", None) is not None
            and status_value in {ProductStatus.ON_MODERATION.value, ProductStatus.BLOCKED.value}
        )
        if not (currently_moderated or has_prior_publication):
            return False
        if product.deleted:
            return False
        hold_until = getattr(product, "safety_hold_until", None)
        if hold_until is not None and hold_until > datetime.now(timezone.utc):
            return False
        return any(self._active_quantity(sku) > 0 for sku in product.skus)

    def _public_product_short(self, product: Product) -> dict[str, object]:
        published = getattr(product, "published_snapshot", None) or {}
        title = published.get("title", product.title)
        description = published.get("description", product.description)
        category = published.get("category", product.category)
        category_id = published.get("category_id", str(product.category_id) if product.category_id else None)
        brand_id = published.get("brand_id", str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None)
        images = ProductResponse._normalize_images(published.get("images", product.images), product.id)
        characteristics = published.get("characteristics", product.characteristics)
        minimum_price = self._published_min_price(product, published)
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": title,
            "description": description,
            "category": category,
            "category_id": category_id,
            "brand_id": brand_id,
            "slug": self._product_slug(product),
            "images": images,
            "image": images[0]["url"] if images else "",
            "characteristics": ProductResponse._normalize_characteristics(
                characteristics
            ),
            "status": ProductStatus.MODERATED.value if published else self._status_value(product.status),
            "price": minimum_price,
            "price_minor": minimum_price,
            "currency": getattr(product.skus[0], "currency", "RUB") if product.skus else "RUB",
            "in_stock": True,
            "is_in_cart": False,
            "min_price": minimum_price,
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
        }

    def _public_product_detail(
        self,
        product: Product,
        *,
        include_unavailable_skus: bool = False,
        pii_codes: set[str] | None = None,
    ) -> dict[str, object]:
        pii_codes = pii_codes or set()
        published = getattr(product, "published_snapshot", None) or {}
        title = published.get("title", product.title)
        description = published.get("description", product.description)
        category = published.get("category", product.category)
        category_id = published.get("category_id", str(product.category_id) if product.category_id else None)
        brand_id = published.get("brand_id", str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None)
        images = ProductResponse._normalize_images(published.get("images", product.images), product.id)
        characteristics = published.get("characteristics", product.characteristics)
        minimum_price = self._published_min_price(product, published)
        published_skus = {str(item["id"]): item for item in published.get("skus", []) if item.get("id")}
        metadata = self._without_pii(characteristics, pii_codes) if isinstance(characteristics, dict) else {}
        try:
            rating = float(metadata.get("rating", 0.0))
        except (TypeError, ValueError):
            rating = 0.0
        try:
            reviews_count = int(metadata.get("reviews_count", 0))
        except (TypeError, ValueError):
            reviews_count = 0
        return {
            "id": str(product.id),
            "seller_id": str(product.seller_id),
            "title": title,
            "description": description,
            "category": category,
            "category_id": category_id,
            "brand_id": brand_id,
            "slug": self._product_slug(product),
            "images": images,
            "image": images[0]["url"] if images else "",
            "price": minimum_price,
            "price_minor": minimum_price,
            "currency": getattr(product.skus[0], "currency", "RUB") if product.skus else "RUB",
            "in_stock": True,
            "is_in_cart": False,
            "characteristics": ProductResponse._normalize_characteristics(
                self._without_pii(characteristics, pii_codes)
            ),
            "status": ProductStatus.MODERATED.value if published else self._status_value(product.status),
            "blocking_reason_id": ProductResponse._blocking_reason_id(
                {"blocking_reason": getattr(product, "blocking_reason", None)}
            ),
            "moderator_comment": ProductResponse._moderator_comment(
                {
                    "blocking_reason": getattr(product, "blocking_reason", None),
                    "field_reports": getattr(product, "field_reports", []),
                }
            ),
            "deleted": product.deleted,
            "created_at": getattr(product, "created_at", datetime.now(timezone.utc)),
            "updated_at": getattr(product, "updated_at", datetime.now(timezone.utc)),
            "rating": rating,
            "reviews_count": reviews_count,
            "skus": [
                self._public_sku_detail(sku, published_skus.get(str(sku.id)), pii_codes)
                for sku in product.skus
                if include_unavailable_skus or self._active_quantity(sku) > 0
            ],
        }

    def _public_sku_detail(
        self,
        sku: object,
        published: dict[str, object] | None = None,
        pii_codes: set[str] | None = None,
    ) -> dict[str, object]:
        published = published or {}
        pii_codes = pii_codes or set()
        price = published.get("price", sku.price)
        options = published.get("options", getattr(sku, "options", getattr(sku, "characteristics", [])))
        return {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "name": published.get("name", sku.name),
            "price": price,
            "price_minor": price,
            "currency": published.get("currency", getattr(sku, "currency", "RUB")),
            "discount": getattr(sku, "discount", 0),
            "article": getattr(sku, "seller_article", getattr(sku, "article", None)),
            "characteristics": ProductResponse._normalize_characteristics(
                self._without_pii(options, pii_codes)
            ),
            "stock_quantity": sku.stock,
            "active_quantity": self._active_quantity(sku),
            "images": published.get("images", sku.images),
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

    def _published_min_price(self, product: Product, snapshot: dict[str, object]) -> int | None:
        by_id = {str(item["id"]): item for item in snapshot.get("skus", []) if item.get("id")}
        prices = [
            by_id.get(str(sku.id), {}).get("price", sku.price)
            for sku in product.skus
            if self._active_quantity(sku) > 0 and by_id.get(str(sku.id), {}).get("price", sku.price) is not None
        ]
        return min(prices) if prices else None

    def _product_slug(self, product: Product) -> str:
        return getattr(product, "slug", None) or ProductResponse._slug(
            product.title, product.id
        )

    def _active_quantity(self, sku: object) -> int:
        on_hand = getattr(sku, "on_hand", None)
        base = sku.stock if on_hand is None else on_hand
        return base - getattr(sku, "reserved_quantity", 0)

    def _status_value(self, product_status: object) -> str:
        if isinstance(product_status, ProductStatus):
            return product_status.value
        return str(product_status)

    async def create(self, seller_id: UUID, data: ProductCreate) -> Product:
        category = await self.repo.session.get(Category, data.category_id)
        if category is None or not category.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"},
            )
        await self._validate_category_attributes(
            category, {item.name: item.value for item in data.characteristics}
        )
        await self._validate_product_brand(data.brand_id)
        product = await self.repo.create_product(
            seller_id=seller_id,
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            brand_id=data.brand_id,
            images=[image.url for image in data.images],
            characteristics={
                characteristic.name: characteristic.value
                for characteristic in data.characteristics
            },
        )
        return await self.repo.get_with_skus(product.id)

    async def create_with_first_sku(
        self, seller_id: UUID, data: ProductWithFirstSKUCreate, idempotency_key: str
    ) -> Product:
        payload = json.dumps(
            data.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        request_hash = hashlib.sha256(payload).hexdigest()
        existing = await self.repo.session.scalar(
            select(SellerProductCreation).where(
                SellerProductCreation.seller_id == seller_id,
                SellerProductCreation.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return await self._replay_product_creation(existing, request_hash)

        product = await self.create(seller_id, data.product)
        await SKUService(self.repo.session).create(
            seller_id,
            SKUCreate(
                product_id=product.id,
                name=data.first_sku.name,
                price=data.first_sku.price,
                stock=data.first_sku.stock,
                images=[
                    {"url": image.url, "ordering": image.ordering}
                    for image in data.first_sku.images
                ],
            ),
        )
        self.repo.session.add(
            SellerProductCreation(
                seller_id=seller_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                product_id=product.id,
            )
        )
        try:
            await self.repo.session.flush()
        except IntegrityError:
            # Product, SKU, outbox event, and receipt share this transaction. A
            # losing concurrent retry rolls all of them back before it reads
            # the winning receipt.
            await self.repo.session.rollback()
            existing = await self.repo.session.scalar(
                select(SellerProductCreation).where(
                    SellerProductCreation.seller_id == seller_id,
                    SellerProductCreation.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            return await self._replay_product_creation(existing, request_hash)
        return await self.repo.get_with_skus(product.id)

    async def create_draft_with_variants(
        self,
        seller_id: UUID,
        data: ProductDraftCreate,
        idempotency_key: str,
    ) -> ProductDraftResponse:
        approved_media: list[SellerMediaAsset] = []
        if data.media_ids:
            if len(set(data.media_ids)) != len(data.media_ids):
                raise HTTPException(status_code=422, detail={"code": "INVALID_MEDIA_ORDER", "message": "Media IDs must be unique"})
            approved_media = list((await self.repo.session.scalars(
                select(SellerMediaAsset).where(
                    SellerMediaAsset.seller_id == seller_id,
                    SellerMediaAsset.id.in_(data.media_ids),
                )
            )).all())
            if len(approved_media) != len(data.media_ids):
                raise HTTPException(status_code=404, detail={"code": "MEDIA_NOT_FOUND", "message": "One or more media assets were not found"})
            if any(asset.state != "READY" or not asset.public_url for asset in approved_media):
                raise HTTPException(status_code=409, detail={"code": "MEDIA_NOT_READY", "message": "All media assets must pass security review before attaching"})
            by_id = {asset.id: asset for asset in approved_media}
            approved_media = [by_id[asset_id] for asset_id in data.media_ids]
        payload = json.dumps(
            data.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        request_hash = hashlib.sha256(payload).hexdigest()
        session = self.repo.session
        existing = await session.scalar(
            select(SellerProductCreation).where(
                SellerProductCreation.seller_id == seller_id,
                SellerProductCreation.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return await self._replay_product_draft(existing, request_hash)

        category = await self.repo.session.get(Category, data.category_id)
        if category is None or not category.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"},
            )
        await self._validate_category_attributes(category, data.attributes)
        await self._validate_variant_options(category, data.variants)
        await self._validate_product_brand(data.brand_id)

        product = Product(
            seller_id=seller_id,
            title=data.title,
            description=data.description,
            category_id=data.category_id,
            brand_id=data.brand_id,
            images=[asset.public_url for asset in approved_media],
            characteristics=data.attributes,
            status=ProductStatus.CREATED,
            is_active=False,
            deleted=False,
            revision=1,
        )
        session.add(product)
        await session.flush()
        skus = [
            SKU(
                product_id=product.id,
                name=variant.name,
                price=variant.price_minor,
                stock=variant.on_hand,
                on_hand=variant.on_hand,
                reserved_quantity=0,
                images=[],
                is_active=True,
                revision=1,
                seller_article=variant.seller_article,
                currency=variant.currency,
                options=variant.options,
            )
            for variant in data.variants
        ]
        session.add_all(skus)
        await self._record_product_version(product, skus)
        operation = SellerProductCreation(
            seller_id=seller_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            product_id=product.id,
            operation_id=uuid4(),
        )
        session.add(operation)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(SellerProductCreation).where(
                    SellerProductCreation.seller_id == seller_id,
                    SellerProductCreation.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            return await self._replay_product_draft(existing, request_hash)
        return self._product_draft_response(product, skus, operation.operation_id)

    async def _validate_category_attributes(
        self, category: Category, attributes: dict[str, object]
    ) -> None:
        # New published rules inherit root-to-leaf and override the parent rule
        # for the same attribute. Unmigrated categories keep their legacy schema.
        lineage: list[Category] = []
        current: Category | None = category
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise HTTPException(status_code=503, detail={"code": "CATEGORY_HIERARCHY_INVALID", "message": "Category hierarchy contains a cycle"})
            seen.add(current.id)
            lineage.append(current)
            current = await self.repo.session.get(Category, current.parent_id) if current.parent_id else None
        if not any(item.schema_version > 0 for item in lineage):
            self._validate_legacy_category_attributes(category, attributes)
            return

        effective_rules: dict[UUID, dict[str, object]] = {}
        for item in reversed(lineage):
            if item.schema_version == 0:
                continue
            if not isinstance(item.attribute_rules, list):
                raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category rules are invalid"})
            for rule in item.attribute_rules:
                if not isinstance(rule, dict) or rule.get("condition") is not None:
                    raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_UNSUPPORTED", "message": "Published category rule cannot be evaluated"})
                try:
                    attribute_id = UUID(str(rule["attribute_id"]))
                except (KeyError, ValueError, TypeError) as exc:
                    raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category rule has an invalid attribute reference"}) from exc
                effective_rules[attribute_id] = rule

        definitions = list((await self.repo.session.scalars(
            select(AttributeDefinition).where(
                AttributeDefinition.id.in_(effective_rules.keys() or {UUID(int=0)}),
                AttributeDefinition.status == "ACTIVE",
            )
        )).all())
        definition_by_id = {definition.id: definition for definition in definitions}
        if definition_by_id.keys() != effective_rules.keys():
            raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category schema references an unavailable attribute"})
        definitions_by_code = {definition.code: definition for definition in definitions}
        errors: list[dict[str, str]] = []
        for key in attributes.keys() - definitions_by_code.keys():
            errors.append({"field_path": f"/attributes/{key}", "code": "UNKNOWN_ATTRIBUTE", "message": "Attribute is not defined for this category"})
        for attribute_id, rule in effective_rules.items():
            definition = definition_by_id[attribute_id]
            key = definition.code
            value = attributes.get(key)
            required = bool(rule.get("required")) or definition.required
            if required and (value is None or (isinstance(value, str) and not value.strip())):
                errors.append({"field_path": f"/attributes/{key}", "code": "REQUIRED", "message": f"{definition.name} is required"})
                continue
            if value is None:
                continue
            error = self._attribute_value_error(definition, value)
            if error:
                errors.append({"field_path": f"/attributes/{key}", "code": error, "message": f"{definition.name} has an invalid value"})
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CATEGORY_ATTRIBUTES_INVALID",
                    "message": "Product attributes do not match the selected category",
                    "invalid_params": errors,
                },
            )

    async def _validate_variant_options(
        self, category: Category, variants: list[DraftVariantInput]
    ) -> None:
        """Validate SKU option tuples against published variant dimensions."""
        lineage: list[Category] = []
        current: Category | None = category
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise HTTPException(status_code=503, detail={"code": "CATEGORY_HIERARCHY_INVALID", "message": "Category hierarchy contains a cycle"})
            seen.add(current.id)
            lineage.append(current)
            current = await self.repo.session.get(Category, current.parent_id) if current.parent_id else None
        if not any(item.schema_version > 0 for item in lineage):
            return

        effective_rules: dict[UUID, dict[str, object]] = {}
        for item in reversed(lineage):
            if item.schema_version == 0:
                continue
            if not isinstance(item.attribute_rules, list):
                raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category rules are invalid"})
            for rule in item.attribute_rules:
                if not isinstance(rule, dict) or rule.get("condition") is not None:
                    raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_UNSUPPORTED", "message": "Published category rule cannot be evaluated"})
                try:
                    attribute_id = UUID(str(rule["attribute_id"]))
                except (KeyError, ValueError, TypeError) as exc:
                    raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category rule has an invalid attribute reference"}) from exc
                effective_rules[attribute_id] = rule
        definitions = list((await self.repo.session.scalars(
            select(AttributeDefinition).where(
                AttributeDefinition.id.in_(effective_rules.keys() or {UUID(int=0)}),
                AttributeDefinition.status == "ACTIVE",
            )
        )).all())
        definition_by_id = {definition.id: definition for definition in definitions}
        if definition_by_id.keys() != effective_rules.keys():
            raise HTTPException(status_code=503, detail={"code": "CATEGORY_SCHEMA_INVALID", "message": "Published category schema references an unavailable attribute"})
        dimensions = {
            definition.code
            for attribute_id, definition in definition_by_id.items()
            if bool(effective_rules[attribute_id].get("variant_dimension")) or definition.variant_dimension
        }
        if not dimensions:
            return

        errors: list[dict[str, str]] = []
        tuples: set[tuple[tuple[str, str], ...]] = set()
        for index, variant in enumerate(variants):
            options = variant.options
            for key in options.keys() - dimensions:
                errors.append({"field_path": f"/variants/{index}/options/{key}", "code": "UNKNOWN_VARIANT_DIMENSION", "message": "Variant option is not a published variant dimension"})
            missing = dimensions - options.keys()
            for key in sorted(missing):
                errors.append({"field_path": f"/variants/{index}/options/{key}", "code": "REQUIRED_VARIANT_DIMENSION", "message": "Every variant must define each variant dimension"})
            if missing or options.keys() - dimensions:
                continue
            if any(not isinstance(value, str) or not value.strip() for value in options.values()):
                errors.append({"field_path": f"/variants/{index}/options", "code": "INVALID_VARIANT_DIMENSION", "message": "Variant dimension values must be non-empty strings"})
                continue
            option_tuple = tuple(sorted((key, value.strip()) for key, value in options.items()))
            if option_tuple in tuples:
                errors.append({"field_path": f"/variants/{index}/options", "code": "DUPLICATE_VARIANT_DIMENSIONS", "message": "Variant dimension combinations must be unique"})
            tuples.add(option_tuple)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "VARIANT_DIMENSIONS_INVALID",
                    "message": "Product variants do not match the category variant dimensions",
                    "invalid_params": errors,
                },
            )

    @staticmethod
    def _attribute_value_error(definition: AttributeDefinition, value: object) -> str | None:
        constraints = definition.constraints if isinstance(definition.constraints, dict) else {}
        data_type = definition.data_type
        numeric: Decimal | None = None
        if data_type == "string":
            if not isinstance(value, str):
                return "INVALID_TYPE"
            pattern = constraints.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str) or len(pattern) > 128 or re.search(r"\\[1-9]|\([^)]*[+*][^)]*\)[+*{]", pattern):
                    return "UNSUPPORTED_CONSTRAINT"
                try:
                    if re.fullmatch(pattern, value) is None:
                        return "PATTERN_MISMATCH"
                except re.error:
                    return "UNSUPPORTED_CONSTRAINT"
            if isinstance(constraints.get("min_length"), int) and len(value) < constraints["min_length"]:
                return "BELOW_MIN_LENGTH"
            if isinstance(constraints.get("max_length"), int) and len(value) > constraints["max_length"]:
                return "ABOVE_MAX_LENGTH"
        elif data_type == "integer":
            if type(value) is not int:
                return "INVALID_TYPE"
            numeric = Decimal(value)
        elif data_type == "decimal":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                return "INVALID_TYPE"
            try:
                numeric = Decimal(str(value))
            except InvalidOperation:
                return "INVALID_TYPE"
            if not numeric.is_finite():
                return "INVALID_TYPE"
        elif data_type == "boolean":
            if type(value) is not bool:
                return "INVALID_TYPE"
        elif data_type in {"enum", "multi_enum"}:
            allowed = constraints.get("allowed_values", constraints.get("options"))
            if not isinstance(allowed, list) or not allowed or any(not isinstance(option, str) for option in allowed):
                return "UNSUPPORTED_CONSTRAINT"
            values = value if data_type == "multi_enum" else [value]
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                return "INVALID_TYPE"
            if data_type == "multi_enum" and len(values) != len(set(values)):
                return "DUPLICATE_VALUE"
            if any(item not in allowed for item in values):
                return "INVALID_OPTION"
        elif data_type == "date":
            if not isinstance(value, str):
                return "INVALID_TYPE"
            try:
                date.fromisoformat(value)
            except ValueError:
                return "INVALID_DATE"
        elif data_type == "reference":
            try:
                UUID(str(value))
            except (ValueError, TypeError):
                return "INVALID_REFERENCE"
        else:
            return "UNSUPPORTED_TYPE"

        if numeric is not None:
            for key, code in (("min", "BELOW_MINIMUM"), ("max", "ABOVE_MAXIMUM")):
                bound = constraints.get(key)
                if bound is not None:
                    try:
                        decimal_bound = Decimal(str(bound))
                    except InvalidOperation:
                        return "UNSUPPORTED_CONSTRAINT"
                    if numeric < decimal_bound if key == "min" else numeric > decimal_bound:
                        return code
        return None

    @staticmethod
    def _validate_legacy_category_attributes(
        category: Category, attributes: dict[str, object]
    ) -> None:
        schema = category.attribute_schema or []
        if not schema:
            return
        definitions = {field["key"]: field for field in schema}
        errors: list[dict[str, str]] = []
        for key in attributes.keys() - definitions.keys():
            errors.append(
                {
                    "field_path": f"/attributes/{key}",
                    "code": "UNKNOWN_ATTRIBUTE",
                    "message": "Attribute is not defined for this category",
                }
            )
        for key, definition in definitions.items():
            value = attributes.get(key)
            if definition.get("required") and (
                value is None or (isinstance(value, str) and not value.strip())
            ):
                errors.append(
                    {
                        "field_path": f"/attributes/{key}",
                        "code": "REQUIRED",
                        "message": f"{definition['label']} is required",
                    }
                )
                continue
            if value is None:
                continue
            if definition.get("value_type") == "number":
                try:
                    float(value)
                except (TypeError, ValueError):
                    errors.append(
                        {
                            "field_path": f"/attributes/{key}",
                            "code": "INVALID_NUMBER",
                            "message": f"{definition['label']} must be a number",
                        }
                    )
            if definition.get("value_type") == "select" and value not in definition.get(
                "options", []
            ):
                errors.append(
                    {
                        "field_path": f"/attributes/{key}",
                        "code": "INVALID_OPTION",
                        "message": f"Select a valid {definition['label']} option",
                    }
                )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "CATEGORY_ATTRIBUTES_INVALID",
                    "message": "Product attributes do not match the selected category",
                    "invalid_params": errors,
                },
            )

    async def _replay_product_draft(
        self, operation: SellerProductCreation, request_hash: str
    ) -> ProductDraftResponse:
        if operation.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "Idempotency-Key was already used for a different product command",
                },
            )
        product = await self.repo.get_with_skus(operation.product_id)
        if product is None or product.seller_id != operation.seller_id:
            raise HTTPException(status_code=404, detail="Product not found")
        return self._product_draft_response(product, product.skus, operation.operation_id)

    async def get_draft_by_idempotency_key(
        self, seller_id: UUID, idempotency_key: str
    ) -> ProductDraftResponse:
        """Recover an atomic draft after the client lost the create response.

        The lookup is always scoped by the authenticated seller.  The
        idempotency key is the only durable value the new-product form keeps
        before the response arrives, so this gives the UI a server-backed
        recovery path instead of relying solely on sessionStorage.
        """
        operation = await self.repo.session.scalar(
            select(SellerProductCreation).where(
                SellerProductCreation.seller_id == seller_id,
                SellerProductCreation.idempotency_key == idempotency_key,
            )
        )
        if operation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DRAFT_OPERATION_NOT_FOUND",
                    "message": "Product draft operation was not found",
                },
            )
        product = await self.repo.get_with_skus(operation.product_id)
        if product is None or product.seller_id != seller_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DRAFT_OPERATION_NOT_FOUND", "message": "Product draft operation was not found"},
            )
        return self._product_draft_response(product, product.skus, operation.operation_id)

    def _product_draft_response(
        self,
        product: Product,
        skus: list[SKU],
        operation_id: UUID,
    ) -> ProductDraftResponse:
        return ProductDraftResponse(
            id=product.id,
            revision=product.revision,
            status="DRAFT",
            operation_id=operation_id,
            variants=[
                {
                    "id": sku.id,
                    "seller_article": sku.seller_article,
                    "name": sku.name,
                    "price_minor": sku.price,
                    "currency": sku.currency,
                    "on_hand": sku.on_hand if sku.on_hand is not None else sku.stock,
                    "options": sku.options,
                }
                for sku in sorted(skus, key=lambda item: (item.seller_article or "").casefold())
            ],
        )

    async def _replay_product_creation(
        self, operation: SellerProductCreation, request_hash: str
    ) -> Product:
        if operation.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "Idempotency-Key was already used for a different product command",
                },
            )
        product = await self.repo.get_with_skus(operation.product_id)
        if product is None or product.seller_id != operation.seller_id:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    async def update(
        self,
        product_id: UUID,
        seller_id: UUID,
        data: ProductUpdate,
        *,
        expected_revision: int | None = None,
        submit_for_moderation: bool = True,
    ) -> Product:
        locked_loader = getattr(self.repo, "get_seller_product_for_update", None)
        product = (
            await locked_loader(product_id, seller_id)
            if callable(locked_loader)
            else await self.repo.get_with_skus(product_id)
        )
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
        current_revision = int(getattr(product, "revision", 1))
        if expected_revision is not None and current_revision != expected_revision:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={
                    "code": "REVISION_CONFLICT",
                    "message": "Product revision is stale",
                    "current_revision": current_revision,
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
        if not submit_for_moderation and product.status != ProductStatus.BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DRAFT_EDIT_NOT_ALLOWED",
                    "message": "Only a blocked product can be saved as an unsubmitted correction draft",
                },
            )

        # Taxonomy validation applies when an edit changes the category or
        # structured attributes.  A title-only edit must not retroactively
        # invalidate an older published product while the grandfather policy
        # is in effect.
        if data.category_id is not None or data.characteristics is not None:
            target_category_id = data.category_id or product.category_id
            session_get = getattr(self.repo.session, "get", None)
            if target_category_id is not None and callable(session_get):
                target_category = await session_get(Category, target_category_id)
                if target_category is None or not target_category.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={
                            "code": "CATEGORY_NOT_FOUND",
                            "message": "Category not found",
                        },
                    )
                target_attributes = (
                    {
                        characteristic.name: characteristic.value
                        for characteristic in data.characteristics
                    }
                    if data.characteristics is not None
                    else dict(product.characteristics or {})
                )
                await self._validate_category_attributes(target_category, target_attributes)

        moderation_client = ModerationClient()
        json_before = moderation_client.product_snapshot(product)
        if data.title is not None:
            product.title = data.title
        if data.description is not None:
            product.description = data.description
        if data.category_id is not None:
            await self._ensure_category_exists(data.category_id)
            product.category_id = data.category_id
        if "brand_id" in data.model_fields_set:
            await self._validate_product_brand(data.brand_id)
            product.brand_id = data.brand_id
        if data.images is not None:
            product.images = [image.url if hasattr(image, "url") else str(image) for image in data.images]
        if getattr(data, "characteristics", None) is not None:
            product.characteristics = {
                characteristic.name: characteristic.value
                for characteristic in data.characteristics
            }
        if getattr(data, "category", None) is not None:
            product.category = data.category
        if getattr(data, "is_active", None) is not None:
            product.is_active = data.is_active
        product.revision = current_revision + 1
        should_send_to_moderation = submit_for_moderation and product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        if should_send_to_moderation:
            product.status = ProductStatus.ON_MODERATION
        await self._record_product_version(product, product.skus)
        await self.repo.session.flush()
        if should_send_to_moderation:
            if hasattr(self.repo.session, "add") and hasattr(
                moderation_client, "build_product_edited_event"
            ):
                event = moderation_client.build_product_edited_event(
                    product, json_before=json_before
                )
                await OutboxEventRepository(self.repo.session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
            else:
                await moderation_client.send_product_edited(
                    product, json_before=json_before
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

    async def _validate_product_brand(self, brand_id: UUID | None) -> None:
        if brand_id is None:
            return
        brand = await self.repo.session.get(Brand, brand_id)
        if brand is None or brand.status != "VERIFIED" or brand.merged_into_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "BRAND_NOT_VERIFIED", "message": "Products may reference only a verified canonical brand"},
            )

    async def _record_product_version(self, product: Product, skus: list[SKU]) -> None:
        if not hasattr(self.repo.session, "add"):
            return
        snapshot = {
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "category_id": str(product.category_id) if product.category_id else None,
            "brand_id": str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None,
            "images": list(product.images or []),
            "characteristics": dict(product.characteristics or {}),
            "skus": [
                {
                    "id": str(sku.id),
                    "name": sku.name,
                    "price": sku.price,
                    "currency": getattr(sku, "currency", "RUB"),
                    "seller_article": getattr(sku, "seller_article", None),
                    "options": getattr(sku, "options", {}) or {},
                    "images": getattr(sku, "images", []) or [],
                }
                for sku in sorted(skus, key=lambda item: str(item.id))
            ],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.repo.session.add(
            ProductVersion(
                product_id=product.id,
                seller_id=product.seller_id,
                revision=product.revision,
                status=str(product.status),
                snapshot=snapshot,
                snapshot_hash=snapshot_hash,
                is_published=False,
            )
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
        moderation_client = ModerationClient()
        if hasattr(self.repo.session, "add") and hasattr(
            moderation_client, "build_product_deleted_event"
        ):
            moderation_event = moderation_client.build_product_deleted_event(product)
            await OutboxEventRepository(self.repo.session).create_event(
                destination="MODERATION",
                idempotency_key=moderation_event["idempotency_key"],
                event_type=moderation_event["event_type"],
                payload=moderation_event,
            )
        else:
            try:
                await moderation_client.send_product_deleted(product)
            except httpx.HTTPError:
                pass
        b2c_client = B2CClient()
        if hasattr(self.repo.session, "add"):
            event = b2c_client.build_product_deleted_event(product)
            await OutboxEventRepository(self.repo.session).create_b2c_event(
                idempotency_key=event["idempotency_key"],
                event_type=event["event"],
                payload={
                    "event_type": event["event"],
                    "idempotency_key": event["idempotency_key"],
                    "occurred_at": event["date"],
                    "payload": {
                        "product_id": event["product_id"],
                        "sku_ids": event["sku_ids"],
                        "reason": event.get("reason"),
                    },
                },
            )
        else:
            try:
                await b2c_client.send_product_deleted(product)
            except httpx.HTTPError:
                pass
