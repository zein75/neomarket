from uuid import uuid4
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.schemas.moderation import BlockDecisionRequest, ProductEventRequest


def test_product_event_rejects_unknown_fields_and_missing_product():
    with pytest.raises(ValidationError):
        ProductEventRequest(event_type="PRODUCT_EDITED", unexpected=True)


def test_product_event_accepts_legacy_defaults():
    event = ProductEventRequest(event_type="PRODUCT_EDITED", product_id=uuid4())
    assert event.idempotency_key == "legacy"
    assert event.occurred_at.tzinfo is not None


def test_product_event_rejects_invalid_name_and_naive_time():
    with pytest.raises(ValidationError):
        ProductEventRequest(
            event_type="product edited",
            product_id=uuid4(),
            occurred_at=datetime(2026, 1, 1),
        )


def test_block_decision_allows_null_field_reports():
    decision = BlockDecisionRequest(blocking_reason_ids=[uuid4()], field_reports=None)
    assert decision.field_reports is None
