from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.moderation_event import ModerationDecisionEvent, ModerationEventRequest


def test_decision_event_rejects_naive_occurred_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ModerationDecisionEvent(
            idempotency_key=uuid4(),
            product_id=uuid4(),
            status="MODERATED",
            occurred_at=datetime(2026, 10, 14, 12, 0),
        )


def test_request_rejects_naive_occurred_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ModerationEventRequest(
            idempotency_key=uuid4(),
            product_id=uuid4(),
            event_type="MODERATED",
            occurred_at=datetime(2026, 10, 14, 12, 0),
        )


def test_timezone_aware_occurred_at_is_accepted() -> None:
    occurred_at = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    event = ModerationDecisionEvent(
        idempotency_key=uuid4(),
        product_id=uuid4(),
        status="MODERATED",
        occurred_at=occurred_at,
    )
    request = ModerationEventRequest(
        idempotency_key=uuid4(),
        product_id=uuid4(),
        event_type="MODERATED",
        occurred_at=occurred_at,
    )

    assert event.occurred_at == occurred_at
    assert request.occurred_at == occurred_at
