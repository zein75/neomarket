from pathlib import Path

from src.models.outbox_event import OutboxEvent


def test_outbox_has_retry_and_lease_columns():
    columns = set(OutboxEvent.__table__.c.keys())
    assert {"next_retry_at", "lease_owner", "lease_until", "last_error"} <= columns


def test_outbox_retry_migration_exists():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0024_outbox_retry_leases.py"
    assert path.exists()
