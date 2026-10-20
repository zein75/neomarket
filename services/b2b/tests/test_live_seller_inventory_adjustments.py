import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.core.config import settings
from src.models.inventory_ledger import InventoryLedger
from src.models.inventory_order_lifecycle import InventoryOrderLifecycle, ReservationLine
from src.models.outbox_event import OutboxEvent
from src.models.product import Product, ProductStatus
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser
from src.models.reservation import Reservation
from src.models.reservation_operation import ReservationOperation
from src.models.sku import SKU
from src.models.stock_adjustment import StockAdjustment


@pytest.mark.postgres_integration
def test_live_inventory_adjustments_preserve_idempotency_and_ledger() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for inventory integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_ids = [uuid4(), uuid4()]
        user_ids = [uuid4(), uuid4()]
        sku_ids = [uuid4(), uuid4(), uuid4()]
        product_ids = [uuid4(), uuid4()]
        emails = [f"inventory-{uuid4()}@example.com" for _ in range(2)]
        password = "DisposableInventory!2026"
        created_at = datetime.now(timezone.utc)
        key = str(uuid4())
        race_order_id, reserve_key = uuid4(), uuid4()
        try:
            async with sessions() as session:
                password_hash = hash_password(password)
                for index in range(2):
                    seller_id, user_id = seller_ids[index], user_ids[index]
                    email = emails[index]
                    session.add_all(
                        [
                            Seller(
                                id=seller_id,
                                email=email,
                                hashed_password=password_hash,
                                company_name=f"Disposable inventory seller {index}",
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
                for index in range(2):
                    session.add(
                        SellerMembership(
                            seller_id=seller_ids[index],
                            user_id=user_ids[index],
                            role="OWNER",
                            active=True,
                        )
                    )
                await session.commit()
                for index in range(2):
                    product = Product(
                        id=product_ids[index],
                        seller_id=seller_ids[index],
                        title=f"Disposable inventory product {index}",
                        description="Inventory adjustment integration fixture",
                        category_id=None,
                        images=[],
                        characteristics={},
                        status=ProductStatus.MODERATED if index == 1 else ProductStatus.CREATED,
                        is_active=index == 1,
                        deleted=False,
                        revision=1,
                    )
                    session.add(product)
                    sku_indexes = (0, 1) if index == 0 else (2,)
                    for sku_index in sku_indexes:
                        session.add(
                            SKU(
                                id=sku_ids[sku_index],
                                product_id=product_ids[index],
                                name=f"Disposable inventory SKU {sku_index}",
                                price=100,
                                stock=0,
                                on_hand=0,
                                reserved_quantity=0,
                                images=[],
                                is_active=True,
                                revision=1,
                            )
                        )
                await session.commit()

            with httpx.Client(timeout=20) as client:
                tokens = []
                for email in emails:
                    login = client.post(
                        f"{b2b_url}/auth/login",
                        data={"username": email, "password": password},
                    )
                    assert login.status_code == 200, login.text
                    tokens.append(login.json()["access_token"])

                endpoint = f"{b2b_url}/api/v1/seller/skus/{sku_ids[0]}/stock-adjustments"
                headers = {"Authorization": f"Bearer {tokens[0]}", "Idempotency-Key": key}
                receipt = client.post(
                    endpoint,
                    headers=headers,
                    json={"delta": 10, "reason": "Initial receipt"},
                )
                assert receipt.status_code == 200, receipt.text
                assert receipt.json()["stock_quantity"] == 10

                status_url = f"{b2b_url}/api/v1/seller/inventory/adjustments/{key}"
                operation_status = client.get(status_url, headers={"Authorization": f"Bearer {tokens[0]}"})
                assert operation_status.status_code == 200, operation_status.text
                assert operation_status.json() == {
                    "operation_id": operation_status.json()["operation_id"],
                    "status": "COMMITTED",
                    "sku_id": str(sku_ids[0]),
                    "delta": 10,
                    "on_hand": 10,
                    "reserved": 0,
                    "available": 10,
                    "ledger_entry_id": operation_status.json()["ledger_entry_id"],
                    "as_of": operation_status.json()["as_of"],
                }
                assert operation_status.json()["ledger_entry_id"]
                hidden_status = client.get(status_url, headers={"Authorization": f"Bearer {tokens[1]}"})
                assert hidden_status.status_code == 404
                missing_status = client.get(
                    f"{b2b_url}/api/v1/seller/inventory/adjustments/{uuid4()}",
                    headers={"Authorization": f"Bearer {tokens[0]}"},
                )
                assert missing_status.status_code == 404

                replay = client.post(
                    endpoint,
                    headers=headers,
                    json={"delta": 10, "reason": "Initial receipt"},
                )
                assert replay.status_code == 200
                assert replay.json()["stock_quantity"] == 10

                changed_delta = client.post(
                    endpoint,
                    headers=headers,
                    json={"delta": 11, "reason": "Initial receipt"},
                )
                assert changed_delta.status_code == 409

                other_sku_same_key = client.post(
                    f"{b2b_url}/api/v1/seller/skus/{sku_ids[1]}/stock-adjustments",
                    headers=headers,
                    json={"delta": 1, "reason": "Initial receipt"},
                )
                assert other_sku_same_key.status_code == 409

                other_tenant_same_key = client.post(
                    f"{b2b_url}/api/v1/seller/skus/{sku_ids[2]}/stock-adjustments",
                    headers={"Authorization": f"Bearer {tokens[1]}", "Idempotency-Key": key},
                    json={"delta": 3, "reason": "Tenant-specific receipt"},
                )
                assert other_tenant_same_key.status_code == 200, other_tenant_same_key.text
                assert other_tenant_same_key.json()["stock_quantity"] == 3

                async def increment_concurrently(index: int) -> httpx.Response:
                    async with httpx.AsyncClient(timeout=30) as async_client:
                        return await async_client.post(
                            f"{b2b_url}/api/v1/seller/skus/{sku_ids[2]}/stock-adjustments",
                            headers={
                                "Authorization": f"Bearer {tokens[1]}",
                                "Idempotency-Key": str(uuid4()),
                            },
                            json={"delta": 1, "reason": f"Concurrent count {index:02}"},
                        )

                concurrent_responses = await asyncio.gather(
                    *(increment_concurrently(index) for index in range(50))
                )
                assert all(response.status_code == 200 for response in concurrent_responses)
                assert max(response.json()["stock_quantity"] for response in concurrent_responses) == 53

                async with httpx.AsyncClient(timeout=30) as race_reserve:
                    reserve_response, adjustment_response = await asyncio.gather(
                        race_reserve.post(
                            f"{b2b_url}/internal/v1/inventory/reserve",
                            headers={"X-Service-Key": settings.service_key},
                            json={
                                "order_id": str(race_order_id),
                                "idempotency_key": str(reserve_key),
                                "items": [{"sku_id": str(sku_ids[2]), "quantity": 50}],
                            },
                        ),
                        race_reserve.post(
                            f"{b2b_url}/api/v1/seller/skus/{sku_ids[2]}/stock-adjustments",
                            headers={
                                "Authorization": f"Bearer {tokens[1]}",
                                "Idempotency-Key": str(uuid4()),
                            },
                            json={"delta": -4, "reason": "Concurrent writeoff"},
                        ),
                    )
                assert reserve_response.status_code in {201, 409}, reserve_response.text
                assert adjustment_response.status_code in {200, 409}, adjustment_response.text
                assert not (
                    reserve_response.status_code == 201
                    and adjustment_response.status_code == 200
                )

                async with sessions() as session:
                    sku = await session.get(SKU, sku_ids[0])
                    assert sku is not None
                    sku.reserved_quantity = 4
                    await session.commit()

                below_reserved = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {tokens[0]}", "Idempotency-Key": str(uuid4())},
                    json={"delta": -7, "reason": "Writeoff"},
                )
                assert below_reserved.status_code == 409

                valid_writeoff = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {tokens[0]}", "Idempotency-Key": str(uuid4())},
                    json={"delta": -5, "reason": "Writeoff"},
                )
                assert valid_writeoff.status_code == 200, valid_writeoff.text
                assert valid_writeoff.json()["stock_quantity"] == 5
                assert valid_writeoff.json()["reserved_quantity"] == 4

                zero_delta = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {tokens[0]}", "Idempotency-Key": str(uuid4())},
                    json={"delta": 0, "reason": "Counted zero"},
                )
                assert zero_delta.status_code in {400, 422}

                oversized_delta = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {tokens[0]}", "Idempotency-Key": str(uuid4())},
                    json={"delta": 10_000_001, "reason": "Overflow check"},
                )
                assert oversized_delta.status_code in {400, 422}

            async with sessions() as session:
                adjustments = list(
                    (
                        await session.scalars(
                            select(StockAdjustment).where(
                                StockAdjustment.seller_id == seller_ids[0]
                            )
                        )
                    ).all()
                )
                assert len(adjustments) == 2
                assert sum(row.delta for row in adjustments) == 5
                assert len({row.idempotency_key for row in adjustments}) == 2
                sku = await session.get(SKU, sku_ids[0])
                assert sku is not None
                assert sku.on_hand == sku.stock == 5
                assert sku.reserved_quantity == 4
                ledger_total = await session.scalar(
                    select(func.coalesce(func.sum(InventoryLedger.delta_on_hand), 0)).where(
                        InventoryLedger.sku_id == sku_ids[0]
                    )
                )
                assert ledger_total == sku.on_hand
                second_seller_adjustment_count = await session.scalar(
                    select(func.count()).select_from(StockAdjustment).where(
                        StockAdjustment.seller_id == seller_ids[1]
                    )
                )
                assert second_seller_adjustment_count == 51 + (adjustment_response.status_code == 200)
                second_seller_sku = await session.get(SKU, sku_ids[2])
                assert second_seller_sku is not None
                second_seller_ledger_total = await session.scalar(
                    select(func.coalesce(func.sum(InventoryLedger.delta_on_hand), 0)).where(
                        InventoryLedger.sku_id == sku_ids[2]
                    )
                )
                assert second_seller_ledger_total == second_seller_sku.on_hand
                assert second_seller_sku.on_hand >= second_seller_sku.reserved_quantity
        finally:
            async with sessions() as session:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_([*sku_ids, *product_ids])))
                await session.execute(delete(Reservation).where(Reservation.order_id == race_order_id))
                await session.execute(delete(ReservationOperation).where(ReservationOperation.idempotency_key == str(reserve_key)))
                await session.execute(delete(ReservationLine).where(ReservationLine.order_id == race_order_id))
                await session.execute(delete(InventoryOrderLifecycle).where(InventoryOrderLifecycle.order_id == race_order_id))
                await session.execute(
                    delete(InventoryLedger).where(InventoryLedger.sku_id.in_(sku_ids))
                )
                await session.execute(
                    delete(StockAdjustment).where(StockAdjustment.seller_id.in_(seller_ids))
                )
                await session.execute(delete(SKU).where(SKU.id.in_(sku_ids)))
                await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                await session.execute(
                    delete(SellerMembership).where(SellerMembership.user_id.in_(user_ids))
                )
                await session.execute(delete(SellerUser).where(SellerUser.id.in_(user_ids)))
                await session.execute(delete(Seller).where(Seller.id.in_(seller_ids)))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
