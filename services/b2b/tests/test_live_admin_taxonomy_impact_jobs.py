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
from src.models.category import Category
from src.models.product import Product
from src.models.seller import Seller
from src.models.taxonomy_impact_job import TaxonomyImpactJob, TaxonomyImpactRedirect
from src.models.taxonomy_impact_preview import TaxonomyImpactPreview
from src.models.taxonomy_state import TaxonomyState
from src.services.taxonomy_impact_job_service import TaxonomyImpactJobService


@pytest.mark.postgres_integration
def test_large_taxonomy_move_preview_resumes_from_durable_category_checkpoint() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        old_parent_id, moving_id, destination_id, seller_id, product_id = (uuid4() for _ in range(5))
        child_ids = [uuid4() for _ in range(5000)]
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
                if await session.get(TaxonomyState, 1) is None:
                    session.add(TaxonomyState(id=1, version=1))
                session.add_all(
                    [
                        Category(id=old_parent_id, code=f"job-old-{old_parent_id.hex}", slug=f"job-old-{old_parent_id.hex}", name="Old parent"),
                        Category(id=moving_id, code=f"job-moving-{moving_id.hex}", slug=f"job-moving-{moving_id.hex}", name="Moving", parent_id=old_parent_id),
                        Category(id=destination_id, code=f"job-dest-{destination_id.hex}", slug=f"job-dest-{destination_id.hex}", name="Destination"),
                        Seller(
                            id=seller_id,
                            email=f"taxonomy-job-{seller_id.hex}@example.invalid",
                            hashed_password="not-used",
                            company_name="Taxonomy job seller",
                            is_active=True,
                            account_status="ACTIVE",
                        ),
                        Product(
                            id=product_id,
                            seller_id=seller_id,
                            title="Product in large category subtree",
                            category_id=moving_id,
                            characteristics={},
                        ),
                        *[
                            Category(
                                id=child_id,
                                code=f"job-child-{child_id.hex}",
                                slug=f"job-child-{child_id.hex}",
                                name=f"Child {index}",
                                parent_id=moving_id,
                            )
                            for index, child_id in enumerate(child_ids)
                        ],
                    ]
                )
                await session.commit()
                moving = await session.get(Category, moving_id)
                assert moving is not None
                category_version = moving.revision

            request_body = {"change_type": "MOVE", "new_parent_id": str(destination_id)}
            request_headers = {
                **headers,
                "Idempotency-Key": str(preview_id),
                "If-Match": f'"{category_version}"',
            }
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                accepted = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json=request_body,
                    headers=request_headers,
                )
                assert accepted.status_code == 202, accepted.text
                queued = accepted.json()
                assert queued["job_id"] == str(preview_id)
                assert queued["status"] == "QUEUED"
                assert queued["total_categories"] == 5001

                # Commit one bounded batch, then use fresh sessions to model a worker restart.
                async with sessions() as session:
                    assert await TaxonomyImpactJobService(session).process_next() == preview_id
                    await session.commit()
                async with sessions() as session:
                    checkpoint = await session.get(TaxonomyImpactJob, preview_id)
                    assert checkpoint is not None
                    assert checkpoint.status == "RUNNING"
                    assert checkpoint.processed_categories == TaxonomyImpactJobService.BATCH_SIZE
                    assert checkpoint.category_cursor is not None
                progress = await client.get(
                    f"/internal/v1/taxonomy/impact-preview-jobs/{preview_id}",
                    headers=headers,
                )
                assert progress.status_code == 200, progress.text
                assert progress.json()["processed_categories"] == TaxonomyImpactJobService.BATCH_SIZE

                for _ in range(100):
                    async with sessions() as session:
                        await TaxonomyImpactJobService(session).process_next()
                        await session.commit()
                    async with sessions() as session:
                        checkpoint = await session.get(TaxonomyImpactJob, preview_id)
                        assert checkpoint is not None
                        if checkpoint.status in {"COMPLETED", "FAILED"}:
                            break

                async with sessions() as session:
                    completed = await session.get(TaxonomyImpactJob, preview_id)
                    assert completed is not None
                    assert completed.status == "COMPLETED", completed.error_code
                    assert completed.processed_categories == 5001
                    assert completed.processed_products == 1
                    assert completed.total_products == 1
                    assert completed.result is not None
                    assert len(completed.result["redirects"]) == 5001
                    assert await session.scalar(
                        select_count_redirects(preview_id)
                    ) == 5001
                    impact_hash = completed.result["hash"]

                replay = await client.post(
                    f"/internal/v1/taxonomy/categories/{moving_id}/impact-preview",
                    json=request_body,
                    headers=request_headers,
                )
                assert replay.status_code == 200, replay.text
                assert replay.json()["hash"] == impact_hash

                command_id = uuid4()
                command = {
                    "command_id": str(command_id),
                    "command_type": "CATEGORY_MOVE",
                    "aggregate_id": str(moving_id),
                    "expected_version": category_version,
                    "impact_hash": impact_hash,
                    "payload": {
                        "new_parent_id": str(destination_id),
                        "impact_hash": impact_hash,
                    },
                    "requested_by_staff_id": str(uuid4()),
                    "approved_by_staff_id": str(uuid4()),
                    "reason_code": "TAXONOMY_CHANGE",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                command_headers = {**headers, "Idempotency-Key": str(command_id), "If-Match": f'"{category_version}"'}
                applied = await client.post("/internal/v1/taxonomy/commands", json=command, headers=command_headers)
                assert applied.status_code == 200, applied.text
                assert applied.json()["status"] == "APPLIED"
                replayed_command = await client.post("/internal/v1/taxonomy/commands", json=command, headers=command_headers)
                assert replayed_command.status_code == 200, replayed_command.text
                assert replayed_command.json() == applied.json()
            async with sessions() as session:
                moved = await session.get(Category, moving_id)
                assert moved is not None and moved.parent_id == destination_id
                receipt = await session.get(TaxonomyImpactPreview, preview_id)
                assert receipt is not None and receipt.consumed_by_command_id == command_id
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(delete(TaxonomyImpactPreview).where(TaxonomyImpactPreview.id == preview_id))
                await session.execute(delete(TaxonomyImpactJob).where(TaxonomyImpactJob.id == preview_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.execute(delete(Category).where(Category.id.in_([old_parent_id, moving_id, destination_id, *child_ids])))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())


def select_count_redirects(job_id):
    from sqlalchemy import func, select

    return select(func.count(TaxonomyImpactRedirect.category_id)).where(
        TaxonomyImpactRedirect.job_id == job_id
    )
