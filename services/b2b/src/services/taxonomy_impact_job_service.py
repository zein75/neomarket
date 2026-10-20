from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.category import Category
from src.models.product import Product
from src.models.taxonomy_impact_job import TaxonomyImpactJob, TaxonomyImpactRedirect
from src.models.taxonomy_impact_preview import TaxonomyImpactPreview
from src.models.taxonomy_state import TaxonomyState
from src.schemas.admin_taxonomy import CategoryRulePayload, TaxonomyImpactPreviewResponse
from src.schemas.taxonomy_impact_jobs import TaxonomyImpactJobResponse
from src.services.product_service import ProductService


class TaxonomyImpactJobService:
    BATCH_SIZE = 200

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _descendants(category_id: UUID):
        subtree = select(Category.id.label("id")).where(Category.id == category_id).cte(
            name="taxonomy_subtree", recursive=True
        )
        return subtree.union(
            select(Category.id.label("id")).join(subtree, Category.parent_id == subtree.c.id)
        )

    @staticmethod
    def _paths(categories: list[Category]) -> dict[UUID, str]:
        by_id = {item.id: item for item in categories}
        children: dict[UUID | None, list[Category]] = defaultdict(list)
        for item in categories:
            children[item.parent_id].append(item)
        paths: dict[UUID, str] = {}
        stack = [(item, "") for item in children[None]]
        while stack:
            category, parent_path = stack.pop()
            if category.id in paths:
                raise ValueError("CATEGORY_HIERARCHY_INVALID")
            path = f"{parent_path}/{category.slug}"
            paths[category.id] = path
            stack.extend((child, path) for child in children[category.id])
        if len(paths) != len(by_id):
            raise ValueError("CATEGORY_HIERARCHY_INVALID")
        return paths

    async def process_next(self) -> UUID | None:
        job = await self.session.scalar(
            select(TaxonomyImpactJob)
            .where(TaxonomyImpactJob.status.in_({"QUEUED", "RUNNING"}))
            .order_by(TaxonomyImpactJob.created_at, TaxonomyImpactJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None

        state = await self.session.scalar(
            select(TaxonomyState).where(TaxonomyState.id == 1).with_for_update()
        )
        category = await self.session.scalar(
            select(Category).where(Category.id == job.category_id).with_for_update()
        )
        if state is None or category is None:
            job.status = "FAILED"
            job.error_code = "TAXONOMY_SOURCE_MISSING"
            return job.id
        if state.version != job.taxonomy_version or category.revision != job.category_version:
            job.status = "FAILED"
            job.error_code = "TAXONOMY_SOURCE_CHANGED"
            return job.id

        subtree = self._descendants(job.category_id)
        if job.status == "QUEUED":
            job.status = "RUNNING"
            job.total_categories = int(
                await self.session.scalar(select(func.count()).select_from(subtree)) or 0
            )
            job.total_products = int(
                await self.session.scalar(
                    select(func.count(Product.id)).where(
                        Product.category_id.in_(select(subtree.c.id)), Product.deleted.is_(False)
                    )
                ) or 0
            )
            if job.change_type == "ARCHIVE":
                warnings: list[str] = []
                has_direct_child = await self.session.scalar(
                    select(Category.id).where(Category.parent_id == category.id).limit(1)
                )
                direct_product_count = int(await self.session.scalar(
                    select(func.count(Product.id)).where(
                        Product.category_id == category.id, Product.deleted.is_(False)
                    )
                ) or 0)
                if has_direct_child is not None:
                    warnings.append("CATEGORY_HAS_CHILDREN")
                if direct_product_count:
                    warnings.append("CATEGORY_HAS_PRODUCTS")
                job.warnings = warnings

        if job.stage == "CATEGORIES":
            stmt = select(Category).where(Category.id.in_(select(subtree.c.id)))
            if job.category_cursor is not None:
                stmt = stmt.where(Category.id > job.category_cursor)
            batch = list((await self.session.scalars(stmt.order_by(Category.id).limit(self.BATCH_SIZE))).all())
            if batch:
                if job.change_type == "MOVE":
                    all_categories = list((await self.session.scalars(select(Category))).all())
                    try:
                        old_paths = self._paths(all_categories)
                    except ValueError:
                        job.status = "FAILED"
                        job.error_code = "CATEGORY_HIERARCHY_INVALID"
                        return job.id
                    original_parent_id = category.parent_id
                    parent_id = UUID(str(job.request["new_parent_id"]))
                    parent = await self.session.get(Category, parent_id)
                    if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
                        job.status = "FAILED"
                        job.error_code = "CATEGORY_PARENT_INVALID"
                        return job.id
                    category.parent_id = parent_id
                    try:
                        new_paths = self._paths(all_categories)
                    except ValueError:
                        job.status = "FAILED"
                        job.error_code = "CATEGORY_HIERARCHY_INVALID"
                        return job.id
                    finally:
                        category.parent_id = original_parent_id
                    self.session.add_all([
                        TaxonomyImpactRedirect(
                            job_id=job.id,
                            category_id=item.id,
                            old_path=old_paths[item.id],
                            new_path=new_paths[item.id],
                        )
                        for item in batch
                        if old_paths[item.id] != new_paths[item.id]
                    ])
                job.category_cursor = batch[-1].id
                job.processed_categories += len(batch)
            else:
                job.stage = "PRODUCTS"
                job.category_cursor = None
            return job.id

        if job.stage == "PRODUCTS":
            stmt = select(Product).where(
                Product.category_id.in_(select(subtree.c.id)), Product.deleted.is_(False)
            )
            if job.product_cursor is not None:
                stmt = stmt.where(Product.id > job.product_cursor)
            products = list((await self.session.scalars(
                stmt.order_by(Product.id).limit(self.BATCH_SIZE)
            )).all())
            if not products:
                job.stage = "FINALIZE"
                job.product_cursor = None
                return job.id

            original_parent_id = category.parent_id
            original_schema_version = category.schema_version
            original_attribute_rules = category.attribute_rules
            if job.change_type == "MOVE":
                category.parent_id = UUID(str(job.request["new_parent_id"]))
            elif job.change_type == "SCHEMA_UPDATE":
                try:
                    proposed_rules = [
                        CategoryRulePayload.model_validate(rule).model_dump(mode="json")
                        for rule in job.request.get("proposed_rules", [])
                    ]
                except (TypeError, ValueError):
                    job.status = "FAILED"
                    job.error_code = "INVALID_CATEGORY_RULES"
                    return job.id
                category.schema_version = original_schema_version + 1
                category.attribute_rules = proposed_rules
            service = ProductService(self.session)
            try:
                with self.session.no_autoflush:
                    for product in products:
                        if job.change_type not in {"MOVE", "SCHEMA_UPDATE"}:
                            continue
                        product_category = await self.session.get(Category, product.category_id)
                        if product_category is None:
                            continue
                        try:
                            await service._validate_category_attributes(
                                product_category, product.characteristics or {}
                            )
                        except HTTPException as exc:
                            if exc.status_code == 422:
                                job.invalid_products += 1
                                if product.published_revision is not None:
                                    job.requires_reapproval += 1
                            else:
                                detail = exc.detail if isinstance(exc.detail, dict) else {}
                                job.status = "FAILED"
                                job.error_code = str(detail.get("code", "TAXONOMY_VALIDATION_UNAVAILABLE"))[:64]
                                category.parent_id = original_parent_id
                                return job.id
            finally:
                category.parent_id = original_parent_id
                category.schema_version = original_schema_version
                category.attribute_rules = original_attribute_rules
            job.product_cursor = products[-1].id
            job.processed_products += len(products)
            return job.id

        current_product_count = int(await self.session.scalar(select(func.count(Product.id))) or 0)
        current_products_updated_at = await self.session.scalar(select(func.max(Product.updated_at)))
        if (
            current_product_count != job.source_product_count
            or current_products_updated_at != job.products_updated_at
        ):
            job.status = "FAILED"
            job.error_code = "PRODUCT_SOURCE_CHANGED"
            return job.id
        redirects = list((await self.session.scalars(
            select(TaxonomyImpactRedirect)
            .where(TaxonomyImpactRedirect.job_id == job.id)
            .order_by(func.length(TaxonomyImpactRedirect.old_path), TaxonomyImpactRedirect.old_path)
        )).all())
        if job.processed_categories != job.total_categories or job.processed_products != job.total_products:
            job.status = "FAILED"
            job.error_code = "TAXONOMY_SOURCE_CHANGED"
            return job.id
        job.affected_sellers = int(await self.session.scalar(
            select(func.count(func.distinct(Product.seller_id))).where(
                Product.category_id.in_(select(subtree.c.id)), Product.deleted.is_(False)
            )
        ) or 0)
        warnings = list(job.warnings or [])
        if job.change_type in {"MOVE", "SCHEMA_UPDATE"} and job.total_products:
            published_count = int(await self.session.scalar(
                select(func.count(Product.id)).where(
                    Product.category_id.in_(select(subtree.c.id)),
                    Product.deleted.is_(False),
                    Product.published_revision.is_not(None),
                )
            ) or 0)
            if published_count:
                warnings.append("SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED")
        if job.change_type == "SCHEMA_UPDATE" and job.invalid_products:
            warnings.append("SCHEMA_MIGRATION_POLICY_REQUIRED")
        impact_payload = {
            "category_id": str(job.category_id),
            "change_type": job.change_type,
            "taxonomy_version": job.taxonomy_version,
            "category_version": job.category_version,
            "request": job.request,
            "affected_products": job.total_products,
            "affected_sellers": job.affected_sellers,
            "affected_categories": job.total_categories,
            "invalid_products": job.invalid_products,
            "requires_reapproval": job.requires_reapproval,
            "redirects": [
                {"old_path": item.old_path, "new_path": item.new_path} for item in redirects
            ],
            "warnings": warnings,
        }
        impact_hash = hashlib.sha256(
            json.dumps(impact_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = TaxonomyImpactPreviewResponse(
            change_id=job.id,
            affected_products=job.total_products,
            affected_sellers=job.affected_sellers,
            affected_categories=job.total_categories,
            invalid_products=job.invalid_products,
            requires_reapproval=job.requires_reapproval,
            redirects=[{"old_path": item.old_path, "new_path": item.new_path} for item in redirects],
            warnings=warnings,
            hash=impact_hash,
        )
        preview = TaxonomyImpactPreview(
            id=job.id,
            category_id=job.category_id,
            change_type=job.change_type,
            request_hash=job.request_hash,
            impact_hash=impact_hash,
            taxonomy_version=job.taxonomy_version,
            category_version=job.category_version,
            request=job.request,
            result=result.model_dump(mode="json"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.session.add(preview)
        job.result = result.model_dump(mode="json")
        job.status = "COMPLETED"
        job.stage = "FINALIZE"
        job.error_code = None
        return job.id

    async def get_job(self, job_id: UUID) -> TaxonomyImpactJobResponse | None:
        job = await self.session.get(TaxonomyImpactJob, job_id)
        if job is None:
            return None
        result = TaxonomyImpactPreviewResponse.model_validate(job.result) if job.result else None
        return TaxonomyImpactJobResponse(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            processed_categories=job.processed_categories,
            total_categories=job.total_categories,
            processed_products=job.processed_products,
            total_products=job.total_products,
            error_code=job.error_code,
            result=result,
        )
