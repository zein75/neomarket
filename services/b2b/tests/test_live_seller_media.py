import asyncio
import hashlib
import io
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.category import Category
from src.models.seller import Seller
from src.models.seller_media_asset import SellerMediaAsset
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@pytest.mark.postgres_integration
def test_live_seller_media_scan_ownership_and_safe_derivative() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for media integration")

    async def fixtures() -> tuple[list[tuple[str, str, object, object]], object]:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        rows = []
        try:
            async with sessions() as session:
                category = await session.scalar(select(Category).where(Category.is_active.is_(True)).limit(1))
                assert category is not None
                for _ in range(2):
                    seller_id, user_id, password = uuid4(), uuid4(), "DisposableMedia!2026"
                    email = f"seller-media-{uuid4()}@example.com"
                    now = datetime.now(timezone.utc)
                    digest = hash_password(password)
                    seller = Seller(id=seller_id, email=email, hashed_password=digest, company_name="Disposable media seller", is_active=True, account_status="ACTIVE", email_verified_at=now)
                    user = SellerUser(id=user_id, email=email, hashed_password=digest, is_active=True, email_verified_at=now)
                    session.add_all([seller, user])
                    await session.flush()
                    session.add(SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True))
                    rows.append((email, password, seller_id, user_id))
                await session.commit()
                category_id = category.id
            return rows, category_id
        finally:
            await engine.dispose()

    sellers, category_id = asyncio.run(fixtures())
    asset_ids = []
    try:
        with httpx.Client(timeout=30) as client:
            tokens = []
            for email, password, _seller_id, _user_id in sellers:
                login = client.post(f"{b2b_url}/auth/login", data={"username": email, "password": password})
                assert login.status_code == 200
                tokens.append(login.json()["access_token"])
            headers = [{"Authorization": f"Bearer {token}"} for token in tokens]

            def intent(content: bytes, content_type: str, owner_headers: dict[str, str]) -> tuple[str, str]:
                response = client.post(
                    f"{b2b_url}/api/v1/seller/media/uploads",
                    headers={**owner_headers, "Idempotency-Key": str(uuid4())},
                    json={"size": len(content), "content_type": content_type, "sha256": hashlib.sha256(content).hexdigest()},
                )
                assert response.status_code == 201, response.text
                payload = response.json()
                asset_ids.append(payload["id"])
                return payload["id"], payload["upload_url"]

            # A signed intent cannot be used to replace the bytes whose digest it binds.
            intended = b"expected bytes"
            _asset_id, upload_url = intent(intended, "image/png", headers[0])
            mismatch = client.put(f"{b2b_url}{upload_url}", content=b"different bytes", headers={"Content-Type": "image/png"})
            assert mismatch.status_code == 422

            # EICAR remains inert test text; the real local ClamAV must reject it before image parsing.
            eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
            eicar_id, eicar_url = intent(eicar, "image/png", headers[0])
            uploaded = client.put(f"{b2b_url}{eicar_url}", content=eicar, headers={"Content-Type": "image/png"})
            assert uploaded.status_code == 204
            time.sleep(1.5)
            before_complete = client.get(f"{b2b_url}/api/v1/seller/media/uploads/{eicar_id}", headers=headers[0])
            assert before_complete.status_code == 200 and before_complete.json()["state"] == "UPLOADED"
            client.post(f"{b2b_url}/api/v1/seller/media/uploads/{eicar_id}/complete", headers=headers[0])
            state = None
            for _ in range(30):
                status_response = client.get(f"{b2b_url}/api/v1/seller/media/uploads/{eicar_id}", headers=headers[0])
                assert status_response.status_code == 200
                state = status_response.json()
                if state["state"] in {"READY", "REJECTED"}:
                    break
                time.sleep(1)
            assert state and state["state"] == "REJECTED" and state["error_code"] == "MALWARE_DETECTED"
            assert client.get(f"{b2b_url}/api/v1/media/public/{eicar_id}").status_code == 404
            assert client.get(f"{b2b_url}/api/v1/seller/media/uploads/{eicar_id}", headers=headers[1]).status_code == 404

            # A real JPEG declared as PNG must fail the format/magic check.
            mismatch_source = io.BytesIO()
            Image.new("RGB", (2, 2), "red").save(mismatch_source, format="JPEG")
            mismatch_bytes = mismatch_source.getvalue()
            mismatch_id, mismatch_url = intent(mismatch_bytes, "image/png", headers[0])
            mismatched_upload = client.put(f"{b2b_url}{mismatch_url}", content=mismatch_bytes, headers={"Content-Type": "image/png"})
            assert mismatched_upload.status_code == 204
            client.post(f"{b2b_url}/api/v1/seller/media/uploads/{mismatch_id}/complete", headers=headers[0])
            for _ in range(30):
                mismatch_response = client.get(f"{b2b_url}/api/v1/seller/media/uploads/{mismatch_id}", headers=headers[0])
                assert mismatch_response.status_code == 200
                mismatch_state = mismatch_response.json()
                if mismatch_state["state"] in {"READY", "REJECTED"}:
                    break
                time.sleep(1)
            assert mismatch_state["state"] == "REJECTED" and mismatch_state["error_code"] == "CONTENT_TYPE_MISMATCH"
            assert client.get(f"{b2b_url}/api/v1/media/public/{mismatch_id}").status_code == 404

            # EXIF is used for orientation while encoding, then omitted from the approved derivative.
            source = io.BytesIO()
            image = Image.new("RGB", (2, 3), "navy")
            exif = Image.Exif()
            exif[274] = 6
            image.save(source, format="JPEG", exif=exif)
            jpeg = source.getvalue()
            image_id, image_url = intent(jpeg, "image/jpeg", headers[0])
            uploaded = client.put(f"{b2b_url}{image_url}", content=jpeg, headers={"Content-Type": "image/jpeg"})
            assert uploaded.status_code == 204
            client.post(f"{b2b_url}/api/v1/seller/media/uploads/{image_id}/complete", headers=headers[0])
            for _ in range(30):
                state_response = client.get(f"{b2b_url}/api/v1/seller/media/uploads/{image_id}", headers=headers[0])
                assert state_response.status_code == 200
                state = state_response.json()
                if state["state"] in {"READY", "REJECTED"}:
                    break
                time.sleep(1)
            assert state["state"] == "READY", state
            public = client.get(f"{b2b_url}/api/v1/media/public/{image_id}")
            assert public.status_code == 200
            with Image.open(io.BytesIO(public.content)) as derivative:
                assert derivative.getexif() == {}
                assert derivative.size == (3, 2)

            # A foreign READY media ID is rejected while creating the other seller's draft.
            async def category_attributes() -> dict[str, object]:
                category_engine = create_async_engine(database_url)
                category_sessions = async_sessionmaker(category_engine, expire_on_commit=False, class_=AsyncSession)
                async with category_sessions() as session:
                    category = await session.get(Category, category_id)
                    schema = category.attribute_schema or []
                    result = {}
                    for field in schema:
                        if field.get("required"):
                            options = field.get("options") or []
                            result[field["key"]] = options[0] if options else "integration"
                    await category_engine.dispose()
                    return result
            attributes = asyncio.run(category_attributes())
            body = {"title": "Foreign media ownership fixture", "description": "Must not attach another seller's image", "category_id": str(category_id), "attributes": attributes, "media_ids": [image_id], "variants": [{"seller_article": f"MEDIA-{uuid4()}", "name": "Fixture SKU", "price_minor": 100, "currency": "RUB", "on_hand": 0, "options": {}}]}
            denied = client.post(f"{b2b_url}/seller/v1/products/drafts", headers={**headers[1], "Idempotency-Key": str(uuid4())}, json=body)
            assert denied.status_code == 404 and denied.json().get("code") == "MEDIA_NOT_FOUND", denied.text
    finally:
        async def cleanup() -> None:
            cleanup_engine = create_async_engine(database_url)
            cleanup_sessions = async_sessionmaker(cleanup_engine, expire_on_commit=False, class_=AsyncSession)
            async with cleanup_sessions() as session:
                await session.execute(delete(SellerMediaAsset).where(SellerMediaAsset.id.in_(asset_ids)))
                for _email, _password, seller_id, user_id in sellers:
                    await session.execute(delete(SellerMembership).where(SellerMembership.seller_id == seller_id))
                    await session.execute(delete(SellerUser).where(SellerUser.id == user_id))
                    await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await cleanup_engine.dispose()
        asyncio.run(cleanup())
