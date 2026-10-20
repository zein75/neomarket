import asyncio
import os
from datetime import datetime, timezone
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
from src.models.taxonomy_command_receipt import TaxonomyCommandReceipt
from src.models.taxonomy_state import TaxonomyState


@pytest.mark.postgres_integration
def test_live_schema_preview_counts_invalid_published_products_and_blocks_publish() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        category_id, attribute_id, seller_id, product_id, preview_id, command_id = (uuid4() for _ in range(6))
        previous_app_env = settings.app_env
        settings.app_env = "development"

        async def db_override():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(admin_internal.router)
        app.dependency_overrides[admin_internal.get_db] = db_override
        headers = {"X-Service-Key": settings.service_key}
        try:
            async with sessions() as session:
                state = await session.get(TaxonomyState, 1)
                assert state is not None
                session.add_all(
                    [
                        Category(
                            id=category_id,
                            code=f"schema-preview-{category_id.hex}",
                            slug=f"schema-preview-{category_id.hex}",
                            name="Schema preview fixture",
                            status="ACTIVE",
                            is_active=True,
                            revision=1,
                        ),
                        AttributeDefinition(
                            id=attribute_id,
                            code=f"required_{attribute_id.hex[:12]}",
                            name="Required attribute",
                            data_type="string",
                            status="ACTIVE",
                        ),
                        Seller(
                            id=seller_id,
                            email=f"schema-preview-{seller_id.hex}@example.invalid",
                            hashed_password="test-only",
                            company_name="Schema preview seller",
                            is_active=True,
                            account_status="ACTIVE",
                        ),
                        Product(
                            id=product_id,
                            seller_id=seller_id,
                            title="Published product missing new rule",
                            slug=f"schema-preview-{product_id.hex}",
                            category_id=category_id,
                            characteristics={},
                            published_revision=4,
                            status="MODERATED",
                            is_active=True,
                        ),
                    ]
                )
                await session.commit()

            proposed_rules = [{"attribute_id": str(attribute_id), "required": True}]
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                preview = await client.post(
                    f"/internal/v1/taxonomy/categories/{category_id}/impact-preview",
                    json={"change_type": "SCHEMA_UPDATE", "proposed_rules": proposed_rules},
                    headers={**headers, "Idempotency-Key": str(preview_id), "If-Match": '"1"'},
                )
                assert preview.status_code == 200, preview.text
                result = preview.json()
                assert result["affected_products"] == 1
                assert result["invalid_products"] == 1
                assert result["requires_reapproval"] == 1
                assert "SCHEMA_MIGRATION_POLICY_REQUIRED" in result["warnings"]

                command = {
                    "command_id": str(command_id),
                    "command_type": "ATTRIBUTE_RULES_PUBLISH",
                    "aggregate_id": str(category_id),
                    "expected_version": 1,
                    "impact_hash": result["hash"],
                    "payload": {"schema_version": 1, "rules": proposed_rules, "impact_hash": result["hash"]},
                    "requested_by_staff_id": str(uuid4()),
                    "approved_by_staff_id": str(uuid4()),
                    "reason_code": "ATTRIBUTE_SCHEMA_CHANGE",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                decision = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=command,
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": '"1"'},
                )
                assert decision.status_code == 200, decision.text
                assert decision.json()["status"] == "REJECTED"
                assert decision.json()["result"] == {"code": "SCHEMA_MIGRATION_POLICY_UNCONFIGURED", "invalid_products": 1}

            async with sessions() as session:
                category = await session.get(Category, category_id)
                product = await session.get(Product, product_id)
                assert category is not None
                assert category.schema_version == 0
                assert category.attribute_rules == []
                assert product is not None
                assert product.status == "MODERATED"
                assert product.published_revision == 4
                assert product.is_active is True
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(delete(TaxonomyCommandReceipt).where(TaxonomyCommandReceipt.command_id == command_id))
                await session.execute(delete(TaxonomyImpactPreview).where(TaxonomyImpactPreview.id == preview_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.execute(delete(AttributeDefinition).where(AttributeDefinition.id == attribute_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
