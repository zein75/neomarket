from pathlib import Path

from src.models.outbox_event import OutboxEvent


def test_outbox_has_payload_hash_column():
    assert "payload_sha256" in OutboxEvent.__table__.c.keys()


def test_outbox_hash_migration_exists():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0026_outbox_payload_hash.py"
    assert path.exists()
