import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.inventory_import import InventoryImportJob
from src.models.inventory_ledger import InventoryLedger
from src.models.product import Product, ProductStatus
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser
from src.models.sku import SKU
from src.models.stock_adjustment import StockAdjustment


@pytest.mark.postgres_integration
def test_live_inventory_import_is_dry_run_partial_and_exactly_once() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for inventory import integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id, product_id, sku_id = uuid4(), uuid4(), uuid4(), uuid4()
        email = f"inventory-import-{uuid4()}@example.com"
        password = "DisposableImport!2026"
        created_at = datetime.now(timezone.utc)
        preview_key, commit_key = str(uuid4()), str(uuid4())
        try:
            async with sessions() as session:
                password_hash = hash_password(password)
                session.add_all(
                    [
                        Seller(
                            id=seller_id,
                            email=email,
                            hashed_password=password_hash,
                            company_name="Disposable import seller",
                            is_active=True,
                            account_status="ACTIVE",
                            email_verified_at=created_at,
                        ),
                        SellerUser(
                            id=user_id,
                            email=email,
                            hashed_password=password_hash,
                            is_active=True,
                            email_verified_at=created_at,
                        ),
                    ]
                )
                await session.commit()
                session.add(SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True))
                session.add(
                    Product(
                        id=product_id,
                        seller_id=seller_id,
                        title="Disposable import product",
                        description="Import integration fixture",
                        category_id=None,
                        images=[],
                        characteristics={},
                        status=ProductStatus.CREATED,
                        is_active=False,
                        deleted=False,
                        revision=1,
                    )
                )
                session.add(
                    SKU(
                        id=sku_id,
                        product_id=product_id,
                        name="Disposable import SKU",
                        seller_article="IMPORT-EXACT-ONCE",
                        price=100,
                        stock=8,
                        on_hand=8,
                        reserved_quantity=2,
                        images=[],
                        is_active=True,
                        revision=4,
                    )
                )
                await session.commit()

            with httpx.Client(timeout=20) as client:
                login = client.post(f"{b2b_url}/auth/login", data={"username": email, "password": password})
                assert login.status_code == 200, login.text
                token = login.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": preview_key}
                body = {
                    "mode": "COUNT",
                    "source_sha256": "a" * 64,
                    "reason": "Physical count",
                    "rows": [
                        {"seller_article": "IMPORT-EXACT-ONCE", "on_hand": 12},
                        {"seller_article": "MISSING-ARTICLE", "on_hand": 3},
                    ],
                }
                endpoint = f"{b2b_url}/api/v1/seller/inventory/imports"
                preview = client.post(endpoint, headers=headers, json=body)
                assert preview.status_code == 201, preview.text
                preview_json = preview.json()
                job_id = preview_json["id"]
                assert preview_json["state"] == "PREVIEWED"
                assert [(row["state"], row["error_code"]) for row in preview_json["rows"]] == [
                    ("VALID", None),
                    ("INVALID", "SKU_NOT_FOUND"),
                ]

                async with sessions() as session:
                    sku = await session.get(SKU, sku_id)
                    assert sku is not None and (sku.on_hand, sku.stock, sku.revision) == (8, 8, 4)
                    adjustment_count = await session.scalar(
                        select(func.count()).select_from(StockAdjustment).where(StockAdjustment.sku_id == sku_id)
                    )
                    ledger_count = await session.scalar(
                        select(func.count()).select_from(InventoryLedger).where(InventoryLedger.sku_id == sku_id)
                    )
                    assert adjustment_count == 0
                    assert ledger_count == 0

                import_url = f"{endpoint}/{job_id}"
                assert client.get(import_url, headers={"Authorization": f"Bearer {token}"}).json() == preview_json
                commit_url = f"{import_url}/commit"
                commit_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": commit_key}
                committed = client.post(commit_url, headers=commit_headers)
                assert committed.status_code == 200, committed.text
                result = committed.json()
                assert result["state"] == "PARTIAL"
                assert (result["valid_rows"], result["error_rows"], result["applied_rows"]) == (1, 1, 1)
                assert [row["state"] for row in result["rows"]] == ["APPLIED", "INVALID"]
                assert result["rows"][0]["result_on_hand"] == 12

                replay = client.post(commit_url, headers=commit_headers)
                assert replay.status_code == 200 and replay.json() == result
                other_key = client.post(commit_url, headers={**commit_headers, "Idempotency-Key": str(uuid4())})
                assert other_key.status_code == 409

                async with sessions() as session:
                    sku = await session.get(SKU, sku_id)
                    assert sku is not None and (sku.on_hand, sku.stock, sku.revision) == (12, 12, 5)
                    adjustments = list(
                        (await session.scalars(select(StockAdjustment).where(StockAdjustment.sku_id == sku_id))).all()
                    )
                    ledger = list(
                        (await session.scalars(select(InventoryLedger).where(InventoryLedger.sku_id == sku_id))).all()
                    )
                    assert len(adjustments) == len(ledger) == 1
                    assert adjustments[0].delta == ledger[0].delta_on_hand == 4
                    assert sum(row.delta_on_hand for row in ledger) == sku.on_hand - 8
        finally:
            async with sessions() as session:
                await session.execute(
                    delete(InventoryImportJob).where(InventoryImportJob.seller_id == seller_id)
                )
                await session.execute(delete(InventoryLedger).where(InventoryLedger.sku_id == sku_id))
                await session.execute(delete(StockAdjustment).where(StockAdjustment.seller_id == seller_id))
                await session.execute(delete(SKU).where(SKU.id == sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(SellerMembership).where(SellerMembership.user_id == user_id))
                await session.execute(delete(SellerUser).where(SellerUser.id == user_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
