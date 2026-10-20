import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import admin_internal
from src.core.config import settings
from src.models.attribute_definition import AttributeDefinition
from src.models.category import Category
from src.models.product import Product
from src.models.seller import Seller
from src.models.taxonomy_impact_preview import TaxonomyImpactPreview


@pytest.mark.postgres_integration
def test_live_taxonomy_move_impact_preview_is_accurate_and_idempotent() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        old_parent_id, moving_id, child_id, destination_id = (uuid4() for _ in range(4))
        attribute_id = uuid4()
        seller_ids = [uuid4(), uuid4()]
        product_ids = [uuid4(), uuid4()]
        preview_id = uuid4()

        async def db_override():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(admin_internal.router)
        app.dependency_overrides[admin_internal.get_db] = db_override
        headers = {"X-Service-Key": settings.service_key}
        previous_app_env = settings.app_env
        settings.app_env = "development"
        try:
            async with sessions() as session:
                session.add_all(
                    [
                        Category(id=old_parent_id, code=f"impact-old-{old_parent_id.hex}", slug=f"impact-old-{old_parent_id.hex}", name="Old path"),
                        Category(id=moving_id, code=f"impact-moving-{moving_id.hex}", slug=f"impact-moving-{moving_id.hex}", name="Moving", parent_id=old_parent_id),
                        Category(id=child_id, code=f"impact-child-{child_id.hex}", slug=f"impact-child-{child_id.hex}", name="Child", parent_id=moving_id),
                        Category(
                            id=destination_id,
                            code=f"impact-destination-{destination_id.hex}",
                            slug=f"impact-destination-{destination_id.hex}",
                            name="Destination",
                            schema_version=1,
                            attribute_rules=[{"attribute_id": str(attribute_id), "required": True}],
                        ),
                        AttributeDefinition(
                            id=attribute_id,
                            code=f"impact_required_{attribute_id.hex[:12]}",
                            name="Required after move",
                            data_type="string",
                        ),
                        *[
                            Seller(
                                id=seller_id,
                                email=f"impact-{seller_id.hex}@example.invalid",
                                hashed_password="not-used",
                                company_name=f"Impact seller {index}",
                                is_active=True,
                                account_status="ACTIVE",
                            )
                            for index, seller_id in enumerate(seller_ids)
                        ],
                        Product(
                            id=product_ids[0],
                            seller_id=seller_ids[0],
                            title="Invalid published product",
                            category_id=moving_id,
                            characteristics={},
                            published_revision=1,
                        ),
                        Product(
                            id=product_ids[1],
                            seller_id=seller_ids[1],
                            title="Valid child product",
                            category_id=child_id,
                            characteristics={f"impact_required_{attribute_id.hex[:12]}": "present"},
                        ),
                    ]
                )
                await session.commit()
                moving = await session.get(Category, moving_id)
                assert moving is not None
                category_version = moving.revision

            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                request = {
                    "change_type": "MOVE",
                    "new_parent_id": str(destination_id),
                }
                request_headers = {
                    **headers,
                    "Idempotency-Key": str(preview_id),
                    "If-Match": f'"{category_version}"',
                }
                response = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json=request,
                    headers=request_headers,
                )
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["affected_products"] == 2
                assert result["affected_sellers"] == 2
                assert result["affected_categories"] == 2
                assert result["invalid_products"] == 1
                assert result["requires_reapproval"] == 1
                assert result["redirects"] == [
                    {"old_path": f"/impact-old-{old_parent_id.hex}/impact-moving-{moving_id.hex}", "new_path": f"/impact-destination-{destination_id.hex}/impact-moving-{moving_id.hex}"},
                    {"old_path": f"/impact-old-{old_parent_id.hex}/impact-moving-{moving_id.hex}/impact-child-{child_id.hex}", "new_path": f"/impact-destination-{destination_id.hex}/impact-moving-{moving_id.hex}/impact-child-{child_id.hex}"},
                ]
                assert "SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED" in result["warnings"]
                assert len(result["hash"]) == 64

                replay = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json=request,
                    headers=request_headers,
                )
                assert replay.status_code == 200, replay.text
                assert replay.json() == result

                conflict = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json={**request, "new_parent_id": str(old_parent_id)},
                    headers=request_headers,
                )
                assert conflict.status_code == 409, conflict.text

                cycle = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json={"change_type": "MOVE", "new_parent_id": str(child_id)},
                    headers={**headers, "Idempotency-Key": str(uuid4()), "If-Match": f'"{category_version}"'},
                )
                assert cycle.status_code == 409, cycle.text
                assert cycle.json()["detail"]["code"] == "CATEGORY_MOVE_CYCLE"
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(delete(TaxonomyImpactPreview).where(TaxonomyImpactPreview.id == preview_id))
                await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                await session.execute(delete(Seller).where(Seller.id.in_(seller_ids)))
                await session.execute(delete(AttributeDefinition).where(AttributeDefinition.id == attribute_id))
                await session.execute(delete(Category).where(Category.id.in_([old_parent_id, moving_id, child_id, destination_id])))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
