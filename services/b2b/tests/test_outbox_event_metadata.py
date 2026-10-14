from pathlib import Path

from src.models.outbox_event import OutboxEvent


def test_outbox_declares_event_envelope_metadata():
    columns = OutboxEvent.__table__.c
    assert {"event_id", "schema_version", "aggregate_id", "correlation_id"} <= set(columns.keys())


def test_outbox_metadata_migration_exists():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0022_outbox_event_metadata.py"
    assert path.exists()
