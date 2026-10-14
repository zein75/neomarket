from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.schemas.events import EventEnvelopeV1


def _event(**overrides):
    value = {
        "schema_version": 1,
        "event_id": uuid4(),
        "event_type": "product.updated",
        "producer": "b2b",
        "aggregate_type": "product",
        "aggregate_id": uuid4(),
        "aggregate_version": 1,
        "occurred_at": datetime.now(timezone.utc),
        "correlation_id": uuid4(),
        "payload": {},
    }
    value.update(overrides)
    return value


def test_event_envelope_accepts_v1_event():
    assert EventEnvelopeV1.model_validate(_event()).schema_version == 1


def test_event_envelope_rejects_unknown_fields_and_invalid_version():
    with pytest.raises(ValidationError):
        EventEnvelopeV1.model_validate(_event(extra_field=True))
    with pytest.raises(ValidationError):
        EventEnvelopeV1.model_validate(_event(schema_version=2))
