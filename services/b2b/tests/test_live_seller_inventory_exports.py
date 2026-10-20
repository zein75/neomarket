import asyncio
import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.inventory_export import InventoryExportJob
from src.models.product import Product, ProductStatus
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser
from src.models.sku import SKU
from src.services.inventory_export_service import delete_artifact


@pytest.mark.postgres_integration
def test_live_inventory_export_is_persisted_signed_and_seller_scoped() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    seller_url = os.getenv("NEOMARKET_SELLER_TEST_URL")
    seller_origin = os.getenv("NEOMARKET_SELLER_ORIGIN_TEST_URL")
    if not database_url or not b2b_url or not seller_url or not seller_origin:
        pytest.skip("set PostgreSQL, B2B, Seller URL, and trusted Seller origin for inventory export integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_a, seller_b = uuid4(), uuid4()
        user_a, user_b = uuid4(), uuid4()
        product_id, sku_id = uuid4(), uuid4()
        job_id = None
        password = "DisposableExport!2026"
        email_a = f"inventory-export-{uuid4()}@example.com"
        email_b = f"inventory-export-{uuid4()}@example.com"
        idempotency_key = str(uuid4())
        try:
            password_hash = hash_password(password)
            async with sessions() as session:
                session.add_all([
                    Seller(
                        id=seller_a, email=email_a, hashed_password=password_hash,
                        company_name="Disposable export seller A", is_active=True,
                        account_status="ACTIVE", email_verified_at=datetime.now(timezone.utc),
                    ),
                    Seller(
                        id=seller_b, email=email_b, hashed_password=password_hash,
                        company_name="Disposable export seller B", is_active=True,
                        account_status="ACTIVE", email_verified_at=datetime.now(timezone.utc),
                    ),
                    SellerUser(id=user_a, email=email_a, hashed_password=password_hash, is_active=True, email_verified_at=datetime.now(timezone.utc)),
                    SellerUser(id=user_b, email=email_b, hashed_password=password_hash, is_active=True, email_verified_at=datetime.now(timezone.utc)),
                ])
                await session.commit()
                session.add_all([
                    SellerMembership(seller_id=seller_a, user_id=user_a, role="OWNER", active=True),
                    SellerMembership(seller_id=seller_b, user_id=user_b, role="OWNER", active=True),
                    Product(
                        id=product_id, seller_id=seller_a, title="=2+2", description="Export fixture",
                        category_id=None, images=[], characteristics={}, status=ProductStatus.CREATED,
                        is_active=False, deleted=False, revision=1,
                    ),
                    SKU(
                        id=sku_id, product_id=product_id, name="Formula variant", seller_article="+SKU-1",
                        price=1250, stock=5, on_hand=5, reserved_quantity=2, images=[],
                        is_active=True, revision=1,
                    ),
                ])
                await session.commit()

            with httpx.Client(timeout=20) as client:
                login_a = client.post(f"{b2b_url}/auth/login", data={"username": email_a, "password": password})
                login_b = client.post(f"{b2b_url}/auth/login", data={"username": email_b, "password": password})
                assert login_a.status_code == login_b.status_code == 200
                headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}
                access_cookie = f"nm_seller_access={login_a.json()['access_token']}"
                csrf_response = client.get(
                    f"{seller_url}/api/seller/auth/csrf",
                    headers={"Cookie": access_cookie},
                )
                assert csrf_response.status_code == 200, csrf_response.text
                csrf_token = csrf_response.json()["token"]
                seller_headers = {
                    "Cookie": f"{access_cookie}; nm_seller_csrf={csrf_token}",
                    "Origin": seller_origin,
                    "X-CSRF-Token": csrf_token,
                }
                bff_endpoint = f"{seller_url}/api/seller/inventory/exports"
                b2b_endpoint = f"{b2b_url}/api/v1/seller/inventory/exports"
                request_headers = {**seller_headers, "Idempotency-Key": idempotency_key}
                request_body = {"format": "CSV"}

                created = client.post(bff_endpoint, headers=request_headers, json=request_body)
                assert created.status_code == 202, created.text
                job_id = created.json()["id"]
                assert created.json()["state"] in {"PENDING", "PROCESSING", "READY"}
                replay = client.post(bff_endpoint, headers=request_headers, json=request_body)
                assert replay.status_code == 202 and replay.json()["id"] == job_id
                conflict = client.post(bff_endpoint, headers=request_headers, json={"format": "CSV", "status": "available"})
                assert conflict.status_code == 409
                foreign = client.get(f"{b2b_endpoint}/{job_id}", headers=headers_b)
                assert foreign.status_code == 404

                result = None
                for _ in range(60):
                    response = client.get(f"{bff_endpoint}/{job_id}", headers={"Cookie": access_cookie})
                    assert response.status_code == 200, response.text
                    result = response.json()
                    if result["state"] in {"READY", "FAILED"}:
                        break
                    await asyncio.sleep(0.5)
                assert result and result["state"] == "READY", result
                assert result["row_count"] == 1 and result["sha256"]
                assert result["download_url"].startswith(f"/api/seller/inventory/exports/{job_id}/download?")

                download_url = f"{seller_url}{result['download_url']}"
                download = client.get(download_url, headers={"Cookie": access_cookie})
                assert download.status_code == 200, download.text
                assert "no-store" in download.headers["cache-control"]
                contents = download.content
                assert hashlib.sha256(contents).hexdigest() == result["sha256"]
                csv_text = contents.decode("utf-8-sig")
                assert "'=2+2" in csv_text and "'+SKU-1" in csv_text

                parsed = urlsplit(download_url)
                query = parse_qs(parsed.query)
                signature = query["token"][0]
                query["token"] = [signature[:-1] + ("A" if signature[-1] != "A" else "B")]
                tampered_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))
                rejected = client.get(tampered_url, headers={"Cookie": access_cookie})
                assert rejected.status_code == 403

            async with sessions() as session:
                persisted = await session.get(InventoryExportJob, UUID(job_id))
                assert persisted is not None
                assert persisted.seller_id == seller_a
                assert persisted.state == "READY" and persisted.row_count == 1

        finally:
            if job_id:
                delete_artifact(seller_a, UUID(job_id))
            async with sessions() as session:
                await session.execute(delete(InventoryExportJob).where(InventoryExportJob.seller_id.in_([seller_a, seller_b])))
                await session.execute(delete(SKU).where(SKU.id == sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(SellerMembership).where(SellerMembership.seller_id.in_([seller_a, seller_b])))
                await session.execute(delete(SellerUser).where(SellerUser.id.in_([user_a, user_b])))
                await session.execute(delete(Seller).where(Seller.id.in_([seller_a, seller_b])))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
