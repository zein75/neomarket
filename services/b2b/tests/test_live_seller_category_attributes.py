import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.category import Category
from src.models.product import Product
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_product_creation import SellerProductCreation
from src.models.seller_user import SellerUser
from src.models.sku import SKU


@pytest.mark.postgres_integration
def test_live_category_schema_rejects_missing_required_attributes() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for category schema integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id, category_id = uuid4(), uuid4(), uuid4()
        email = f"category-schema-{uuid4()}@example.com"
        password = "DisposableCategory!2026"
        product_id = None
        try:
            async with sessions() as session:
                now = datetime.now(timezone.utc)
                password_hash = hash_password(password)
                session.add_all(
                    [
                        Seller(
                            id=seller_id,
                            email=email,
                            hashed_password=password_hash,
                            company_name="Disposable category schema seller",
                            is_active=True,
                            account_status="ACTIVE",
                            email_verified_at=now,
                        ),
                        SellerUser(
                            id=user_id,
                            email=email,
                            hashed_password=password_hash,
                            is_active=True,
                            email_verified_at=now,
                        ),
                        Category(
                            id=category_id,
                            name="Disposable category schema",
                            slug=f"category-schema-{category_id}",
                            is_active=True,
                            revision=3,
                            attribute_schema=[
                                {
                                    "key": "manufacturer",
                                    "label": "Manufacturer",
                                    "required": True,
                                    "value_type": "text",
                                },
                                {
                                    "key": "condition",
                                    "label": "Condition",
                                    "required": True,
                                    "value_type": "select",
                                    "options": ["new", "used"],
                                },
                            ],
                        ),
                    ]
                )
                await session.commit()
                session.add(SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True))
                await session.commit()

            with httpx.Client(timeout=20) as client:
                login = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": email, "password": password},
                )
                assert login.status_code == 200, login.text
                headers = {
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "Idempotency-Key": str(uuid4()),
                }
                response = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers=headers,
                    json={
                        "title": "Schema validation fixture",
                        "description": "Category attributes must be validated before writing",
                        "category_id": str(category_id),
                        "attributes": {"condition": "broken"},
                        "variants": [
                            {
                                "seller_article": "CATEGORY-001",
                                "name": "Schema fixture variant",
                                "price_minor": 100,
                                "currency": "RUB",
                                "on_hand": 1,
                            }
                        ],
                    },
                )
                assert response.status_code == 422, response.text
                invalid_params = response.json()["invalid_params"]
                assert {item["field_path"]: item["code"] for item in invalid_params} == {
                    "/attributes/manufacturer": "REQUIRED",
                    "/attributes/condition": "INVALID_OPTION",
                }
                async with sessions() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(Product).where(Product.seller_id == seller_id)
                    ) == 0
                    assert await session.scalar(
                        select(func.count()).select_from(SellerProductCreation).where(
                            SellerProductCreation.seller_id == seller_id
                        )
                    ) == 0

                valid = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={
                        "title": "Schema validation fixture",
                        "description": "Category attributes must be validated before writing",
                        "category_id": str(category_id),
                        "attributes": {"manufacturer": "ExampleCo", "condition": "new"},
                        "variants": [
                            {
                                "seller_article": "CATEGORY-002",
                                "name": "Schema fixture variant",
                                "price_minor": 100,
                                "currency": "RUB",
                                "on_hand": 1,
                            }
                        ],
                    },
                )
                assert valid.status_code == 201, valid.text
                product_id = valid.json()["id"]
                category_list = client.get(
                    f"{b2b_url}/api/v1/seller/categories",
                    headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                )
                assert category_list.status_code == 200
                item = next(value for value in category_list.json()["items"] if value["id"] == str(category_id))
                assert item["revision"] == 3
                assert item["attribute_schema"][0]["key"] == "manufacturer"
        finally:
            async with sessions() as session:
                await session.execute(delete(SellerProductCreation).where(SellerProductCreation.seller_id == seller_id))
                if product_id:
                    await session.execute(delete(SKU).where(SKU.product_id == product_id))
                    await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(SellerMembership).where(SellerMembership.user_id == user_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.execute(delete(SellerUser).where(SellerUser.id == user_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
