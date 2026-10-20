import csv
import hashlib
import io
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.models.inventory_export import InventoryExportJob
from src.schemas.inventory_export import InventoryExportCreate
from src.services.inventory_export_service import (
    InventoryExportService,
    _csv_text,
    _decode_download_token,
    delete_artifact,
)


@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1:A2)", "-2+3", "@cmd"])
def test_inventory_export_csv_text_neutralizes_spreadsheet_formulas(value: str) -> None:
    assert _csv_text(value) == "'" + value


def test_inventory_export_csv_text_preserves_plain_text_and_nulls() -> None:
    assert _csv_text("plain article") == "plain article"
    assert _csv_text(None) == ""


@pytest.mark.postgres_integration
@pytest.mark.asyncio
async def test_inventory_export_is_idempotent_bounded_tenant_scoped_and_expires(tmp_path, monkeypatch) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run the PostgreSQL export integration")

    monkeypatch.setattr(settings, "media_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "inventory_export_max_rows", 10)
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    seller_id, product_id = uuid4(), uuid4()
    idempotency_key = uuid4()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("""
                CREATE TEMP TABLE products (
                    id uuid PRIMARY KEY, seller_id uuid NOT NULL, title varchar(255) NOT NULL,
                    category varchar(100), status varchar(32) NOT NULL,
                    deleted boolean NOT NULL, is_active boolean NOT NULL
                )
            """))
            await connection.execute(text("""
                CREATE TEMP TABLE skus (
                    id uuid PRIMARY KEY, product_id uuid NOT NULL, name varchar(255) NOT NULL,
                    seller_article varchar(128), on_hand bigint, stock bigint NOT NULL,
                    reserved_quantity bigint NOT NULL, is_active boolean NOT NULL, revision integer NOT NULL
                )
            """))
            await connection.execute(text("""
                CREATE TEMP TABLE seller_inventory_exports (
                    id uuid PRIMARY KEY, seller_id uuid NOT NULL, idempotency_key uuid NOT NULL,
                    request_hash varchar(64) NOT NULL, filters json NOT NULL,
                    state varchar(16) NOT NULL, lease_expires_at timestamptz,
                    lease_generation integer NOT NULL DEFAULT 0,
                    generated_at timestamptz, expires_at timestamptz, artifact_removed_at timestamptz,
                    row_count integer NOT NULL DEFAULT 0, attempts integer NOT NULL DEFAULT 0,
                    sha256 varchar(64), failure_code varchar(40),
                    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
                )
            """))
            await connection.execute(text("""
                INSERT INTO products (id, seller_id, title, category, status, deleted, is_active)
                VALUES (:product_id, :seller_id, '=HYPERLINK("https://invalid")', 'QA', 'CREATED', false, true)
            """), {"product_id": product_id, "seller_id": seller_id})
            await connection.execute(text("""
                INSERT INTO skus (id, product_id, name, seller_article, on_hand, stock, reserved_quantity, is_active, revision)
                VALUES
                  ('00000000-0000-0000-0000-000000000001', :product_id, 'Variant one', '+QA-1', 5, 5, 2, true, 1),
                  ('00000000-0000-0000-0000-000000000002', :product_id, 'Variant two', 'QA-2', 3, 3, 1, false, 1)
            """), {"product_id": product_id})

            session_factory = async_sessionmaker(bind=connection, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as session:
                service = InventoryExportService(session)
                job = await service.create(seller_id, idempotency_key, InventoryExportCreate())
                await session.flush()
                original_id = job.id
                replay = await service.create(seller_id, idempotency_key, InventoryExportCreate())
                assert replay.id == original_id
                with pytest.raises(ValueError, match="another export request"):
                    await service.create(
                        seller_id,
                        idempotency_key,
                        InventoryExportCreate(status="available"),
                    )
                await session.commit()

            async with session_factory() as session:
                claim = await InventoryExportService.claim_next(session, datetime.now(timezone.utc))
                assert claim == (original_id, 1)
                await session.commit()

            await InventoryExportService.process(original_id, 1, session_factory)
            async with session_factory() as session:
                service = InventoryExportService(session)
                ready = await service.get(seller_id, original_id)
                assert ready is not None and ready.state == "READY"
                assert ready.row_count == 2 and ready.sha256
                assert await service.get(uuid4(), original_id) is None
                token = service.download_token(ready)
                assert token
                path_info = await service.download_path(original_id, token)
                assert path_info is not None
                path, _ = path_info
                contents = path.read_bytes()
                assert hashlib.sha256(contents).hexdigest() == ready.sha256
                rows = list(csv.reader(io.StringIO(contents.decode("utf-8-sig"))))
                assert rows[1][0].startswith("'=")
                assert rows[1][2].startswith("'+")
                assert len(rows) == 3

                malformed = token.rsplit(".", 1)[0] + ".A" + token.rsplit(".", 1)[1][1:]
                with pytest.raises(ValueError, match="invalid or expired"):
                    _decode_download_token(malformed)

                ready.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await session.commit()
                assert await service.download_path(original_id, token) is None
                now = datetime.now(timezone.utc)
                expired = await InventoryExportService.expire_ready(session, now)
                assert (seller_id, original_id) in expired
                for expired_seller_id, expired_job_id in expired:
                    delete_artifact(expired_seller_id, expired_job_id)
                await session.commit()
                assert not path.exists()

            # The export limit is a hard row bound: no partial artifact is retained.
            monkeypatch.setattr(settings, "inventory_export_max_rows", 1)
            overflow_key = uuid4()
            async with session_factory() as session:
                overflow = await InventoryExportService(session).create(
                    seller_id, overflow_key, InventoryExportCreate()
                )
                overflow_id = overflow.id
                await session.commit()
            async with session_factory() as session:
                overflow_claim = await InventoryExportService.claim_next(session, datetime.now(timezone.utc))
                await session.commit()
            assert overflow_claim == (overflow_id, 1)
            await InventoryExportService.process(overflow_id, 1, session_factory)
            async with session_factory() as session:
                overflow = await InventoryExportService(session).get(seller_id, overflow_id)
            assert overflow is not None
            assert overflow.state == "FAILED"
            assert overflow.failure_code == "EXPORT_ROW_LIMIT_EXCEEDED"
            assert not (tmp_path / "exports" / str(seller_id) / f"{overflow_id}.csv").exists()

            monkeypatch.setattr(settings, "inventory_export_max_rows", 10)
            fenced_key = uuid4()
            async with session_factory() as session:
                fenced = await InventoryExportService(session).create(
                    seller_id, fenced_key, InventoryExportCreate(status="available")
                )
                fenced_id = fenced.id
                await session.commit()
            async with session_factory() as session:
                first_claim = await InventoryExportService.claim_next(session, datetime.now(timezone.utc))
                assert first_claim == (fenced_id, 1)
                await session.commit()
            async with session_factory() as session:
                await session.execute(
                    update(InventoryExportJob)
                    .where(InventoryExportJob.id == fenced_id)
                    .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                )
                second_claim = await InventoryExportService.claim_next(session, datetime.now(timezone.utc))
                assert second_claim == (fenced_id, 2)
                await session.commit()

            await InventoryExportService.process(fenced_id, 1, session_factory)
            stale_artifact = tmp_path / "exports" / str(seller_id) / f"{fenced_id}.csv"
            assert not stale_artifact.exists()
            async with session_factory() as session:
                still_processing = await InventoryExportService(session).get(seller_id, fenced_id)
                assert still_processing is not None and still_processing.state == "PROCESSING"
                assert still_processing.lease_generation == 2
            await InventoryExportService.process(fenced_id, 2, session_factory)
            async with session_factory() as session:
                completed = await InventoryExportService(session).get(seller_id, fenced_id)
                assert completed is not None and completed.state == "READY"
    finally:
        await engine.dispose()
