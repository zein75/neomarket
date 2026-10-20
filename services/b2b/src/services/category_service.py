from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.category import Category
from src.repositories.category_repo import CategoryRepository
from src.schemas.category import (
    CategoryDetailResponse,
    CategoryListResponse,
    CategoryParentResponse,
    CategoryResponse,
)


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CategoryRepository(session)

    async def list_active(self) -> CategoryListResponse:
        categories = await self.repo.list_active()
        return CategoryListResponse(
            items=[self._category_response(category) for category in categories]
        )

    async def get_detail(
        self,
        category_id: UUID,
        *,
        include_product_count: bool = False,
    ) -> CategoryDetailResponse:
        categories = await self.repo.list_active()
        by_id = {category.id: category for category in categories}
        category = by_id.get(category_id)
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Category not found"},
            )
        parent = by_id.get(category.parent_id) if category.parent_id else None
        product_count = (
            await self.repo.count_public_products(category.id)
            if include_product_count
            else None
        )
        product_count_as_of = datetime.now(timezone.utc) if include_product_count else None
        seo_title = getattr(category, "seo_title", None)
        image_media_id = getattr(category, "image_media_id", None)
        return CategoryDetailResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            description=getattr(category, "description", None),
            parent=(
                CategoryParentResponse(
                    id=parent.id,
                    name=parent.name,
                    slug=parent.slug,
                )
                if parent
                else None
            ),
            product_count=product_count,
            product_count_as_of=product_count_as_of,
            seo={"title": seo_title} if seo_title else {},
            meta_tags={},
            image_url=str(image_media_id) if image_media_id else None,
            is_active=category.is_active,
            attribute_schema=getattr(category, "attribute_schema", []),
            revision=getattr(category, "revision", 1),
            created_at=getattr(category, "created_at", datetime.now(timezone.utc)),
            updated_at=getattr(category, "updated_at", datetime.now(timezone.utc)),
        )

    def _category_response(self, category: Category) -> CategoryResponse:
        return CategoryResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            parent_id=category.parent_id,
            is_active=category.is_active,
            attribute_schema=getattr(category, "attribute_schema", []),
            revision=getattr(category, "revision", 1),
            created_at=getattr(category, "created_at", datetime.now(timezone.utc)),
            updated_at=getattr(category, "updated_at", datetime.now(timezone.utc)),
        )
