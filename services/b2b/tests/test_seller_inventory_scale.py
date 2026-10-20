import hashlib
import json
import os
import time
import tracemalloc
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.routers.seller_inventory import _decode_cursor, _encode_cursor
from src.services.inventory_service import SellerInventoryService


@pytest.mark.postgres_integration
@pytest.mark.asyncio
async def test_seller_inventory_cursor_and_aggregation_cover_100k_skus() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run the isolated PostgreSQL scale check")

    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    seller_id = uuid4()
    product_id = uuid4()
    digest = hashlib.sha256()
    rows_seen = 0
    pages_seen = 0
    max_page_size = 0
    started = time.perf_counter()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("""
                CREATE TEMP TABLE products (
                    id uuid PRIMARY KEY,
                    seller_id uuid NOT NULL,
                    title varchar(255) NOT NULL,
                    category varchar(100),
                    status varchar(32) NOT NULL,
                    deleted boolean NOT NULL,
                    is_active boolean NOT NULL
                ) ON COMMIT DROP
            """))
            await connection.execute(text("""
                CREATE TEMP TABLE skus (
                    id uuid PRIMARY KEY,
                    product_id uuid NOT NULL,
                    name varchar(255) NOT NULL,
                    seller_article varchar(128),
                    on_hand bigint,
                    stock bigint NOT NULL,
                    reserved_quantity bigint NOT NULL,
                    is_active boolean NOT NULL,
                    revision integer NOT NULL
                ) ON COMMIT DROP
            """))
            await connection.execute(text("""
                INSERT INTO products (id, seller_id, title, category, status, deleted, is_active)
                VALUES (:product_id, :seller_id, 'Scale fixture', 'QA', 'CREATED', false, true)
            """), {"product_id": product_id, "seller_id": seller_id})
            inserted = await connection.execute(text("""
                INSERT INTO skus (
                    id, product_id, name, seller_article, on_hand, stock,
                    reserved_quantity, is_active, revision
                )
                SELECT
                    ('00000000-0000-0000-0000-' || lpad(to_hex(n), 12, '0'))::uuid,
                    :product_id,
                    'SKU ' || n::text,
                    'QA-' || n::text,
                    2,
                    2,
                    1,
                    true,
                    1
                FROM generate_series(1, 100000) AS n
            """), {"product_id": product_id})
            assert inserted.rowcount == 100000

            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                service = SellerInventoryService(session)
                cursor: tuple[UUID, UUID] | None = None
                tracemalloc.start()
                while True:
                    page = await service.list_for_seller(
                        seller_id, limit=100, cursor=cursor
                    )
                    items = page["items"]
                    assert len(items) <= 100
                    pages_seen += 1
                    max_page_size = max(max_page_size, len(items))
                    for item in items:
                        rows_seen += 1
                        assert item["sku_id"] == UUID(int=rows_seen)
                        assert item["active_quantity"] == 1
                        digest.update(item["sku_id"].bytes)
                    if not page["has_more"]:
                        assert page["next_cursor"] is None
                        break
                    position = page["next_cursor"]
                    assert position is not None
                    cursor_token = _encode_cursor(seller_id, *position, None, None)
                    cursor = _decode_cursor(cursor_token, seller_id)
                    assert cursor == position
                _, peak_bytes = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                metrics = await service.get_dashboard_metrics(seller_id)
                assert metrics["metrics"] == {
                    "live_products": 1,
                    "sku_count": 100000,
                    "total_on_hand": 200000,
                    "available_stock": 100000,
                    "pending_moderation": 0,
                    "reserved_stock": 100000,
                }

            assert rows_seen == 100000
            assert pages_seen == 1000
            assert max_page_size == 100
            assert peak_bytes < 32 * 1024 * 1024
            print("INV16_RESULT " + json.dumps({
                "seller_skus": rows_seen,
                "pages": pages_seen,
                "page_limit": 100,
                "max_page_rows": max_page_size,
                "python_peak_bytes_during_pagination": peak_bytes,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "ordered_id_sha256": digest.hexdigest(),
                "metrics": metrics["metrics"],
                "fixture": "transaction-scoped PostgreSQL temp tables; no persistent rows",
            }, sort_keys=True))
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        await engine.dispose()
