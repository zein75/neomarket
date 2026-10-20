import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import admin_internal, categories
from src.core.config import settings
from src.models.category import Category
from src.models.brand import Brand, BrandAlias
from src.models.attribute_definition import AttributeDefinition
from src.models.seller import Seller
from src.models.product import Product
from src.models.sku import SKU
from src.models.taxonomy_command_receipt import TaxonomyCommandReceipt
from src.models.taxonomy_impact_preview import TaxonomyImpactPreview
from src.models.taxonomy_state import TaxonomyState
from src.services.product_service import ProductService


@pytest.mark.postgres_integration
def test_live_admin_taxonomy_command_is_versioned_and_idempotent() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        category_id, child_id, attribute_id, pii_attribute_id, command_id, schema_preview_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
        seller_id, product_id, count_product_id, count_sku_id, image_media_id, archive_preview_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
        hidden_category_id, hidden_preview_id = uuid4(), uuid4()
        command_ids = [command_id]

        async def db_override():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(admin_internal.router)
        app.include_router(categories.router)
        app.dependency_overrides[admin_internal.get_db] = db_override
        app.dependency_overrides[categories.get_db] = db_override
        headers = {"X-Service-Key": settings.service_key}
        previous_app_env = settings.app_env
        settings.app_env = "development"
        async with sessions() as session:
            state = await session.get(TaxonomyState, 1)
            assert state is not None
            starting_version = state.version
        command = {
            "command_id": str(command_id),
            "command_type": "CATEGORY_CREATE",
            "aggregate_id": str(category_id),
            "expected_version": starting_version,
            "payload": {
                "code": f"admin-{category_id.hex}",
                "slug": f"admin-{category_id.hex}",
                "name": "Admin taxonomy command fixture",
                "labels": {"ru-RU": "Тестовая категория", "en-US": "Test category"},
                "description": "Disposable integration fixture",
                "seo_title": "Admin taxonomy fixture",
                "image_media_id": str(image_media_id),
            },
            "requested_by_staff_id": str(uuid4()),
            "approved_by_staff_id": str(uuid4()),
            "reason_code": "TAXONOMY_CHANGE",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=command,
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": f'"{starting_version}"'},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "APPLIED"
                assert response.json()["result"]["aggregate_version"] == 1

                replay = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=command,
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": f'"{starting_version}"'},
                )
                assert replay.status_code == 200, replay.text
                assert replay.json() == response.json()

                changed = {**command, "payload": {**command["payload"], "name": "Changed payload"}}
                conflict = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=changed,
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": f'"{starting_version}"'},
                )
                assert conflict.status_code == 409, conflict.text

                async def send_taxonomy_command(command_type: str, aggregate_id, expected_version: int, payload: dict[str, object], impact_hash: str | None = None):
                    command_id_value = uuid4()
                    command_ids.append(command_id_value)
                    body = {
                        "command_id": str(command_id_value),
                        "command_type": command_type,
                        "aggregate_id": str(aggregate_id),
                        "expected_version": expected_version,
                        "impact_hash": impact_hash,
                        "payload": payload,
                        "requested_by_staff_id": str(uuid4()),
                        "approved_by_staff_id": str(uuid4()),
                        "reason_code": "TAXONOMY_CHANGE",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    }
                    return await client.post(
                        "/internal/v1/taxonomy/commands",
                        json=body,
                        headers={**headers, "Idempotency-Key": str(command_id_value), "If-Match": f'"{expected_version}"'},
                    )

                duplicate = await send_taxonomy_command(
                    "CATEGORY_CREATE", uuid4(), starting_version + 1,
                    {"code": command["payload"]["code"], "slug": command["payload"]["slug"], "name": "Duplicate category"},
                )
                assert duplicate.status_code == 200 and duplicate.json()["status"] == "REJECTED", duplicate.text
                assert duplicate.json()["result"]["code"] == "CATEGORY_CODE_OR_SLUG_EXISTS"

                child = await send_taxonomy_command(
                    "CATEGORY_CREATE", child_id, starting_version + 1,
                    {"parent_id": str(category_id), "code": f"child-{child_id.hex}", "slug": f"child-{child_id.hex}", "name": "Inherited schema child"},
                )
                assert child.status_code == 200 and child.json()["status"] == "APPLIED", child.text
                attribute = await send_taxonomy_command(
                    "ATTRIBUTE_CREATE", attribute_id, starting_version + 2,
                    {"draft_action": "CREATE", "attribute": {"code": "condition", "name": "Condition", "data_type": "enum", "constraints": {"allowed_values": ["new", "used"]}, "variant_dimension": True}},
                )
                assert attribute.status_code == 200 and attribute.json()["status"] == "APPLIED", attribute.text
                pii_attribute = await send_taxonomy_command(
                    "ATTRIBUTE_CREATE", pii_attribute_id, starting_version + 3,
                    {"draft_action": "CREATE", "attribute": {"code": "contact_email", "name": "Contact email", "data_type": "string", "pii": True}},
                )
                assert pii_attribute.status_code == 200 and pii_attribute.json()["status"] == "APPLIED", pii_attribute.text
                schema_preview = await client.post(
                    f"/internal/v1/taxonomy/categories/{category_id}/impact-preview",
                    json={
                        "change_type": "SCHEMA_UPDATE",
                        "proposed_rules": [{"attribute_id": str(attribute_id), "required": True, "filterable": True, "variant_dimension": True}],
                    },
                    headers={**headers, "Idempotency-Key": str(schema_preview_id), "If-Match": '"1"'},
                )
                assert schema_preview.status_code == 200, schema_preview.text
                schema_impact_hash = schema_preview.json()["hash"]
                rules = await send_taxonomy_command(
                    "ATTRIBUTE_RULES_PUBLISH", category_id, 1,
                    {"schema_version": 1, "rules": [{"attribute_id": str(attribute_id), "required": True, "filterable": True, "variant_dimension": True}], "impact_hash": schema_impact_hash},
                    schema_impact_hash,
                )
                assert rules.status_code == 200 and rules.json()["status"] == "APPLIED", rules.text
                async with sessions() as session:
                    published_schema = await session.get(Category, category_id)
                    assert published_schema is not None
                    assert published_schema.schema_version == 1
                    assert published_schema.attribute_rules[0]["required"] is True
                update_attribute = await send_taxonomy_command(
                    "ATTRIBUTE_UPDATE", attribute_id, 1,
                    {"draft_action": "UPDATE", "attribute": {"code": "condition", "name": "Product condition", "data_type": "enum", "constraints": {"allowed_values": ["new", "used"]}, "required": False, "filterable": True, "variant_dimension": True}},
                )
                assert update_attribute.status_code == 200 and update_attribute.json()["status"] == "APPLIED", update_attribute.text
                stale_attribute = await send_taxonomy_command(
                    "ATTRIBUTE_UPDATE", attribute_id, 1,
                    {"draft_action": "UPDATE", "attribute": {"code": "condition", "name": "Stale condition", "data_type": "enum", "constraints": {"allowed_values": ["new", "used"]}}},
                )
                assert stale_attribute.status_code == 200 and stale_attribute.json()["status"] == "CONFLICT", stale_attribute.text
                category_update = await send_taxonomy_command(
                    "CATEGORY_UPDATE", category_id, 2,
                    {"name": "Renamed taxonomy fixture", "slug": f"renamed-{category_id.hex}"},
                )
                assert category_update.status_code == 200 and category_update.json()["status"] == "APPLIED", category_update.text
                stale_category_update = await send_taxonomy_command(
                    "CATEGORY_UPDATE", category_id, 2,
                    {"name": "Stale taxonomy fixture"},
                )
                assert stale_category_update.status_code == 200 and stale_category_update.json()["status"] == "CONFLICT", stale_category_update.text

                async with sessions() as session:
                    session.add(
                        Seller(
                            id=seller_id,
                            email=f"{seller_id.hex}@example.invalid",
                            hashed_password="test-only",
                            company_name="Taxonomy archive fixture",
                            is_active=True,
                        )
                    )
                    session.add(
                        Product(
                            id=product_id,
                            seller_id=seller_id,
                            title="Referenced category product",
                            slug=f"referenced-{product_id.hex}",
                            category_id=child_id,
                            status="CREATED",
                            is_active=False,
                        )
                    )
                    session.add(
                        Product(
                            id=count_product_id,
                            seller_id=seller_id,
                            title="Root category count product",
                            slug=f"root-count-{count_product_id.hex}",
                            category_id=category_id,
                            status="MODERATED",
                            is_active=True,
                        )
                    )
                    session.add(
                        SKU(
                            id=count_sku_id,
                            product_id=count_product_id,
                            name="Count SKU",
                            price=100,
                            stock=1,
                            on_hand=1,
                            reserved_quantity=0,
                            images=[],
                            is_active=True,
                            options={},
                        )
                    )
                    await session.commit()
                archive_preview = await client.post(
                    f"/internal/v1/taxonomy/categories/{child_id}/impact-preview",
                    json={"change_type": "ARCHIVE"},
                    headers={**headers, "Idempotency-Key": str(archive_preview_id), "If-Match": '"1"'},
                )
                assert archive_preview.status_code == 200, archive_preview.text
                impact_hash = archive_preview.json()["hash"]
                archive_referenced = await send_taxonomy_command(
                    "CATEGORY_ARCHIVE", child_id, 1, {"impact_hash": impact_hash}, impact_hash,
                )
                assert archive_referenced.status_code == 200 and archive_referenced.json()["status"] == "REJECTED", archive_referenced.text
                assert archive_referenced.json()["result"]["code"] == "CATEGORY_HAS_PRODUCTS", archive_referenced.text
                brand_create = await send_taxonomy_command(
                    "BRAND_CREATE", brand_id, starting_version + 7,
                    {"draft_action": "CREATE", "brand": {"name": "Canonical fixture brand", "aliases": ["Legacy fixture", "Old canonical"]}},
                )
                assert brand_create.status_code == 200 and brand_create.json()["status"] == "APPLIED", brand_create.text
                publish_root = await send_taxonomy_command(
                    "CATEGORY_PUBLISH", category_id, 3, {},
                )
                assert publish_root.status_code == 200 and publish_root.json()["status"] == "APPLIED", publish_root.text
                public_categories = await client.get(
                    "/api/v1/public/categories", headers=headers,
                )
                assert public_categories.status_code == 200, public_categories.text
                assert any(item["id"] == str(category_id) for item in public_categories.json()["items"])
                public_detail = await client.get(
                    f"/api/v1/public/categories/{category_id}",
                    headers=headers,
                )
                assert public_detail.status_code == 200, public_detail.text
                assert public_detail.json()["description"] == "Disposable integration fixture"
                assert public_detail.json()["seo"] == {"title": "Admin taxonomy fixture"}
                assert public_detail.json()["image_url"] == str(image_media_id)
                root_detail = await client.get(
                    f"/api/v1/public/categories/{category_id}?include_product_count=true",
                    headers=headers,
                )
                assert root_detail.status_code == 200, root_detail.text
                assert root_detail.json()["product_count"] == 1
                assert root_detail.json()["product_count_as_of"]
                missing_detail = await client.get(
                    f"/api/v1/public/categories/{uuid4()}", headers=headers,
                )
                assert missing_detail.status_code == 404, missing_detail.text
                hidden_create = await send_taxonomy_command(
                    "CATEGORY_CREATE", hidden_category_id, starting_version + 9,
                    {"code": f"hidden-{hidden_category_id.hex}", "slug": f"hidden-{hidden_category_id.hex}", "name": "Hidden category"},
                )
                assert hidden_create.status_code == 200 and hidden_create.json()["status"] == "APPLIED", hidden_create.text
                hidden_preview = await client.post(
                    f"/internal/v1/taxonomy/categories/{hidden_category_id}/impact-preview",
                    json={"change_type": "ARCHIVE"},
                    headers={**headers, "Idempotency-Key": str(hidden_preview_id), "If-Match": '"1"'},
                )
                assert hidden_preview.status_code == 200, hidden_preview.text
                hidden_hash = hidden_preview.json()["hash"]
                hidden_archive = await send_taxonomy_command(
                    "CATEGORY_ARCHIVE", hidden_category_id, 1, {"impact_hash": hidden_hash}, hidden_hash,
                )
                assert hidden_archive.status_code == 200 and hidden_archive.json()["status"] == "APPLIED", hidden_archive.text
                public_after_archive = await client.get(
                    "/api/v1/public/categories", headers=headers,
                )
                assert public_after_archive.status_code == 200, public_after_archive.text
                assert not any(item["id"] == str(hidden_category_id) for item in public_after_archive.json()["items"])

                snapshot = await client.get("/internal/v1/taxonomy/snapshot", headers=headers)
                assert snapshot.status_code == 200, snapshot.text
                assert any(item["id"] == str(attribute_id) for item in snapshot.json()["attributes"])
                snapshot_category = next(item for item in snapshot.json()["categories"] if item["id"] == str(category_id))
                snapshot_brand = next(item for item in snapshot.json()["brands"] if item["id"] == str(brand_id))
                assert snapshot_brand["name"] == "Canonical fixture brand"
                assert {"Legacy fixture", "Old canonical"} <= set(snapshot_brand["aliases"])
                assert snapshot_category["labels"] == {"ru-RU": "Тестовая категория", "en-US": "Test category"}
                async with sessions() as session:
                    child_category = await session.get(Category, child_id)
                    assert child_category is not None
                    service = ProductService(session)
                    pii_codes = await service._pii_attribute_codes()
                    assert "contact_email" in pii_codes
                    assert service._without_pii({"contact_email": "private@example.test", "condition": "new"}, pii_codes) == {"condition": "new"}
                    public_product = SimpleNamespace(
                        id=uuid4(), seller_id=uuid4(), title="PII filter fixture",
                        description="Public product test", category="Fixture",
                        category_id=child_id, brand_id=None, slug="pii-filter-fixture", images=[],
                        characteristics={"contact_email": "private@example.test", "condition": "new"},
                        status="MODERATED", deleted=False, skus=[],
                        published_snapshot={"characteristics": {"contact_email": "private@example.test", "condition": "new"}},
                    )
                    public_view = service._public_product_detail(public_product, pii_codes=pii_codes)
                    assert public_view["characteristics"] == [{"name": "condition", "value": "new"}]
                    with pytest.raises(HTTPException) as required_error:
                        await service._validate_category_attributes(child_category, {})
                    assert getattr(required_error.value, "detail", {}).get("invalid_params", [{}])[0]["code"] == "REQUIRED"
                    with pytest.raises(HTTPException) as enum_error:
                        await service._validate_category_attributes(child_category, {"condition": "broken"})
                    assert getattr(enum_error.value, "detail", {}).get("invalid_params", [{}])[0]["code"] == "INVALID_OPTION"
                    await service._validate_category_attributes(child_category, {"condition": "new"})
                    valid_variants = [
                        SimpleNamespace(options={"condition": "new"}),
                        SimpleNamespace(options={"condition": "used"}),
                    ]
                    await service._validate_variant_options(child_category, valid_variants)
                    with pytest.raises(HTTPException) as duplicate_variant_error:
                        await service._validate_variant_options(
                            child_category,
                            [SimpleNamespace(options={"condition": "new"}), SimpleNamespace(options={"condition": "new"})],
                        )
                    assert getattr(duplicate_variant_error.value, "detail", {}).get("invalid_params", [{}])[0]["code"] == "DUPLICATE_VARIANT_DIMENSIONS"
                    with pytest.raises(HTTPException) as missing_variant_error:
                        await service._validate_variant_options(child_category, [SimpleNamespace(options={})])
                    assert getattr(missing_variant_error.value, "detail", {}).get("invalid_params", [{}])[0]["code"] == "REQUIRED_VARIANT_DIMENSION"

                receipt = await client.get(f"/internal/v1/taxonomy/commands/{command_id}", headers=headers)
                assert receipt.status_code == 200, receipt.text
                assert receipt.json() == response.json()

            async with sessions() as session:
                created = await session.get(Category, category_id)
                assert created is not None
                assert created.name == "Renamed taxonomy fixture"
                assert created.slug == f"renamed-{category_id.hex}"
                assert created.description == "Disposable integration fixture"
                assert created.seo_title == "Admin taxonomy fixture"
                assert created.image_media_id == image_media_id
                assert created.labels == {"ru-RU": "Тестовая категория", "en-US": "Test category"}
                assert created.status == "ACTIVE"
                assert created.is_active is True
                state = await session.get(TaxonomyState, 1)
                assert state is not None and state.version == starting_version + 11
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(delete(TaxonomyCommandReceipt).where(TaxonomyCommandReceipt.command_id.in_(command_ids)))
                await session.execute(delete(TaxonomyImpactPreview).where(TaxonomyImpactPreview.id.in_([archive_preview_id, schema_preview_id])))
                await session.execute(delete(TaxonomyImpactPreview).where(TaxonomyImpactPreview.id == hidden_preview_id))
                await session.execute(delete(AttributeDefinition).where(AttributeDefinition.id.in_([attribute_id, pii_attribute_id])))
                await session.execute(delete(SKU).where(SKU.id == count_sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Product).where(Product.id == count_product_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.execute(delete(BrandAlias).where(BrandAlias.brand_id == brand_id))
                await session.execute(delete(Brand).where(Brand.id == brand_id))
                await session.execute(delete(Category).where(Category.id == hidden_category_id))
                await session.execute(delete(Category).where(Category.id == child_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                state = await session.get(TaxonomyState, 1)
                if state is not None:
                    state.version = starting_version
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
