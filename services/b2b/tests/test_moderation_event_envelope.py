from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.moderation_event import ModerationEventEnvelope


def _event(action: str = "APPROVE") -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": uuid4(),
        "event_type": "moderation.approved",
        "producer": "admin",
        "aggregate_type": "moderation_ticket",
        "aggregate_id": uuid4(),
        "aggregate_version": 1,
        "occurred_at": datetime.now(timezone.utc),
        "correlation_id": uuid4(),
        "payload": {
            "product_id": uuid4(),
            "reviewed_revision": 1,
            "decision_id": uuid4(),
            "ticket_id": uuid4(),
            "actor_id": uuid4(),
            "action": action,
        },
    }


def test_moderation_envelope_is_validated():
    assert ModerationEventEnvelope.model_validate(_event()).payload.action == "APPROVE"


def test_moderation_envelope_rejects_unknown_action():
    with pytest.raises(ValidationError):
        ModerationEventEnvelope.model_validate(_event("DELETE"))


def test_moderation_envelope_preserves_field_level_reports():
    event = _event("BLOCK")
    event["event_type"] = "moderation.blocked"
    event["payload"]["field_reports"] = [
        {
            "field_path": "/description",
            "reason_code": "DESCRIPTION_MISMATCH",
            "comment": "Please correct the description.",
        }
    ]

    parsed = ModerationEventEnvelope.model_validate(event)

    assert parsed.payload.field_reports[0].field_path == "/description"
    assert parsed.payload.field_reports[0].reason_code == "DESCRIPTION_MISMATCH"
