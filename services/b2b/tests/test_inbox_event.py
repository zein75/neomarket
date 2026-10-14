from pathlib import Path

from src.models.inbox_event import InboxEvent


def test_inbox_keys_events_by_producer_and_event_id():
    constraints = {c.name for c in InboxEvent.__table__.constraints if c.name}
    assert "uq_inbox_producer_event" in constraints
    assert InboxEvent.__table__.c.payload_hash.nullable is False


def test_inbox_migration_exists():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0025_inbox_events.py"
    assert path.exists()
