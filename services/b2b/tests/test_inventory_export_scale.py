import hashlib
import os
import time
import tracemalloc
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.schemas.inventory_export import InventoryExportCreate
from src.services.inventory_export_service import InventoryExportService


@pytest.mark.postgres_integration
@pytest.mark.asyncio
async def test_inventory_export_streams_one_hundred_thousand_skus_with_bounded_memory(
    tmp_path, monkeypatch
) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL for the PostgreSQL inventory export scale test")

    monkeypatch.setattr(settings, "media_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "inventory_export_max_rows", 100_000)
    seller_id = uuid4()
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("""
                CREATE TEMP TABLE products (
                    id uuid PRIMARY KEY,
                    seller_id uuid NOT NULL,
                    title varchar(255) NOT NULL,
                    status varchar(32) NOT NULL,
                    deleted boolean NOT NULL
                ) ON COMMIT PRESERVE ROWS
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
                    is_active boolean NOT NULL
                ) ON COMMIT PRESERVE ROWS
            """))
            await connection.execute(text("""
                CREATE TEMP TABLE seller_inventory_exports (
                    id uuid PRIMARY KEY,
                    seller_id uuid NOT NULL,
                    idempotency_key uuid NOT NULL,
                    request_hash varchar(64) NOT NULL,
                    filters json NOT NULL,
                    state varchar(16) NOT NULL,
                    lease_expires_at timestamptz,
                    lease_generation integer NOT NULL DEFAULT 0,
                    generated_at timestamptz,
                    expires_at timestamptz,
                    artifact_removed_at timestamptz,
                    row_count integer NOT NULL DEFAULT 0,
                    attempts integer NOT NULL DEFAULT 0,
                    sha256 varchar(64),
                    failure_code varchar(40),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                ) ON COMMIT PRESERVE ROWS
            """))
            await connection.execute(text("""
                INSERT INTO products (id, seller_id, title, status, deleted)
                SELECT md5('product-' || n)::uuid, :seller_id,
                       'Inventory scale product ' || n, 'CREATED', false
                FROM generate_series(1, 10000) AS gs(n)
            """), {"seller_id": seller_id})
            await connection.execute(text("""
                INSERT INTO skus (
                    id, product_id, name, seller_article, on_hand, stock,
                    reserved_quantity, is_active
                )
                SELECT md5('sku-' || n)::uuid,
                       md5('product-' || ((n + 9) / 10))::uuid,
                       'Variant ' || n, 'SCALE-' || n, 5, 5, 1, true
                FROM generate_series(1, 100000) AS gs(n)
            """))
            await connection.execute(text("CREATE INDEX ON skus (product_id, id)"))
            await connection.commit()

            session_factory = async_sessionmaker(
                bind=connection, class_=AsyncSession, expire_on_commit=False
            )
            async with session_factory() as session:
                job = await InventoryExportService(session).create(
                    seller_id, uuid4(), InventoryExportCreate()
                )
                job_id = job.id
                await session.commit()
            async with session_factory() as session:
                claim = await InventoryExportService.claim_next(session, datetime.now(timezone.utc))
                assert claim == (job_id, 1)
                await session.commit()

            tracemalloc.start()
            started_at = time.perf_counter()
            await InventoryExportService.process(job_id, 1, session_factory)
            _current, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            elapsed_seconds = time.perf_counter() - started_at

            async with session_factory() as session:
                completed = await InventoryExportService(session).get(seller_id, job_id)
                assert completed is not None
                assert completed.state == "READY"
                assert completed.row_count == 100_000
                assert completed.sha256
                artifact = tmp_path / "exports" / str(seller_id) / f"{job_id}.csv"
                assert artifact.is_file()
                digest = hashlib.sha256()
                line_count = 0
                with artifact.open("rb") as stream:
                    for line in stream:
                        digest.update(line)
                        line_count += 1
                assert line_count == 100_001  # header plus all SKU rows
                assert digest.hexdigest() == completed.sha256
                assert peak_bytes < 64 * 1024 * 1024
                if os.name == "posix":
                    assert artifact.stat().st_mode & 0o777 == 0o600
                print({
                    "rows": completed.row_count,
                    "csv_lines_including_header": line_count,
                    "csv_bytes": artifact.stat().st_size,
                    "sha256": completed.sha256,
                    "worker_peak_tracemalloc_bytes": peak_bytes,
                    "worker_elapsed_seconds": round(elapsed_seconds, 3),
                })
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        await engine.dispose()
