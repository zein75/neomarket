"""Verify the evidence-only moderation receipt backfill and repeat safety."""

import asyncio
import json
import os

import asyncpg
import pytest


@pytest.mark.postgres_integration
def test_migration_backfill_replays_receipts_without_creating_rows() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_BACKFILL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_BACKFILL_TEST_DATABASE_URL")
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def scenario() -> None:
        pool = await asyncpg.create_pool(dsn)
        try:
            async with pool.acquire() as connection:
                receipt_count_before = await connection.fetchval(
                    "SELECT count(*) FROM moderation_decision_receipts"
                )
                snapshot_count_before = await connection.fetchval(
                    "SELECT count(*) FROM moderation_snapshots"
                )
                receipt = await connection.fetchrow(
                    """
                    SELECT product_revision, snapshot_hash, policy_version,
                           reason_codes, field_reports
                      FROM moderation_decision_receipts
                     WHERE id = '11111111-1111-4111-8111-111111111111'
                    """
                )
                snapshot_policy_version = await connection.fetchval(
                    """
                    SELECT policy_version
                      FROM moderation_snapshots
                     WHERE id = '22222222-2222-4222-8222-222222222222'
                    """
                )
                historical = await connection.fetchrow(
                    """
                    SELECT product_revision, snapshot_hash, policy_version,
                           reason_codes, field_reports
                      FROM moderation_decision_receipts
                     WHERE id = '33333333-3333-4333-8333-333333333333'
                    """
                )
                assert receipt is not None
                assert receipt["product_revision"] == 7
                assert receipt["snapshot_hash"] == "a" * 64
                assert receipt["policy_version"] == 3
                assert json.loads(receipt["reason_codes"]) == ["MISSING_TITLE"]
                assert json.loads(receipt["field_reports"]) == [
                    {"field_path": "title", "reason_code": "MISSING_TITLE"}
                ]
                assert snapshot_policy_version == 4
                assert historical is not None
                assert all(value is None for value in historical.values())

                assert receipt_count_before == 2
                assert snapshot_count_before == 1
                assert await connection.fetchval("SELECT count(*) FROM audit_logs") == 1
                assert await connection.fetchval("SELECT count(*) FROM moderation_outbox_events") == 1
        finally:
            await pool.close()

    asyncio.run(scenario())
