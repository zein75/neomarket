import asyncio
import hashlib
import json
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
from src.models.product_version import ProductVersion
from src.models.seller import Seller
from src.models.sku import SKU


@pytest.mark.postgres_integration
def test_live_admin_product_reads_use_publication_and_immutable_revision() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database"
        )

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        seller_id, category_id, product_id, sku_id = uuid4(), uuid4(), uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        content = {
            "title": "Disposable Admin internal API fixture",
            "description": "Created only in a disposable PostgreSQL database",
            "category_id": str(category_id),
            "images": ["media://admin-internal/product"],
            "characteristics": {"material": "steel"},
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "Fixture SKU",
                    "price": 12500,
                    "currency": "RUB",
                    "seller_article": "ADMIN-INTERNAL-1",
                    "options": {},
                    "images": ["media://admin-internal/sku"],
                }
            ],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

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
                seller = Seller(
                    id=seller_id,
                    email=f"admin-internal-{product_id}@example.com",
                    hashed_password="disposable-fixture-unused",
                    company_name="Disposable Admin internal fixture",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=now,
                )
                category = Category(
                    id=category_id,
                    name="Disposable Admin internal fixture",
                    slug=f"admin-internal-{product_id}",
                    is_active=True,
                    revision=1,
                )
                product = Product(
                    id=product_id,
                    seller_id=seller_id,
                    title=content["title"],
                    description=content["description"],
                    category_id=category_id,
                    images=content["images"],
                    characteristics=content["characteristics"],
                    status="MODERATED",
                    is_active=True,
                    deleted=False,
                    revision=2,
                    published_revision=1,
                )
                session.add_all([seller, category, product])
                await session.flush()
                sku = SKU(
                    id=sku_id,
                    product_id=product_id,
                    name="Fixture SKU",
                    price=12500,
                    stock=3,
                    on_hand=3,
                    reserved_quantity=0,
                    images=["media://admin-internal/sku"],
                    is_active=True,
                    revision=1,
                    options={},
                )
                version = ProductVersion(
                    product_id=product_id,
                    seller_id=seller_id,
                    revision=1,
                    status="MODERATED",
                    snapshot=content,
                    snapshot_hash=snapshot_hash,
                    is_published=True,
                )
                session.add_all([sku, version])
                await session.commit()

            try:
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    publication = await client.get(
                        f"/internal/v1/products/{product_id}/publication",
                        headers=headers,
                    )
                    revision = await client.get(
                        f"/internal/v1/products/{product_id}/revisions/1",
                        headers=headers,
                    )
                    product_page = await client.get(
                        "/internal/v1/products?search=Disposable%20Admin%20internal%20API%20fixture&limit=10",
                        headers=headers,
                    )
                    taxonomy = await client.get(
                        "/internal/v1/taxonomy/snapshot",
                        headers=headers,
                    )
                assert publication.status_code == 200, publication.text
                assert publication.json()["visible"] is True
                assert publication.json()["current_revision"] == 2
                assert publication.json()["published_revision"] == 1
                assert publication.json()["visibility_reasons"] == []
                assert revision.status_code == 200, revision.text
                assert revision.json()["snapshot_hash"] == snapshot_hash
                assert revision.json()["content"] == content
                assert revision.json()["media_refs"] == [
                    "media://admin-internal/product",
                    "media://admin-internal/sku",
                ]
                assert product_page.status_code == 200, product_page.text
                assert [item["product_id"] for item in product_page.json()["items"]] == [str(product_id)]
                assert product_page.json()["items"][0]["visible"] is True
                assert product_page.json()["page"] == {"has_more": False, "next_cursor": None}
                assert taxonomy.status_code == 200, taxonomy.text
                assert taxonomy.json()["version"] == 1
                assert taxonomy.json()["attributes"] == []
                assert len(taxonomy.json()["categories"]) == 1
                tax_category = taxonomy.json()["categories"][0]
                assert {key: value for key, value in tax_category.items() if key != "updated_at"} == {
                    "id": str(category_id),
                    "parent_id": None,
                    "code": f"admin-internal-{product_id}",
                    "slug": f"admin-internal-{product_id}",
                    "name": "Disposable Admin internal fixture",
                    "description": None,
                    "status": "ACTIVE",
                    "sort_order": None,
                    "version": 1,
                    "path": f"/admin-internal-{product_id}",
                    "seo_title": None,
                    "image_media_id": None,
                    "schema_version": 0,
                    "attribute_rules": [],
                }
                assert tax_category["updated_at"]

                async with sessions() as session:
                    fixture_sku = await session.get(SKU, sku_id)
                    assert fixture_sku is not None
                    fixture_sku.on_hand = 0
                    await session.commit()

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    no_stock = await client.get(
                        f"/internal/v1/products/{product_id}/publication",
                        headers=headers,
                    )
                assert no_stock.status_code == 200, no_stock.text
                assert no_stock.json()["visible"] is False
                assert no_stock.json()["visibility_reasons"] == ["NO_ACTIVE_SKU"]
            finally:
                settings.app_env = previous_app_env
        finally:
            async with sessions() as session:
                await session.execute(
                    delete(ProductVersion).where(
                        ProductVersion.product_id == product_id
                    )
                )
                await session.execute(delete(SKU).where(SKU.id == sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(
                    delete(Category).where(Category.id == category_id)
                )
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
