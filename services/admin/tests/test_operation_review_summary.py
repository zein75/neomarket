from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routers import iam
from src.api.routers.iam import _operation_review_response, approve_operation
from src.schemas.admin import ReasonAction


def _operation(action: str, payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        action=action,
        status="WAITING_APPROVAL",
        entity_type="category",
        entity_id=uuid4(),
        requested_by=uuid4(),
        approved_by=None,
        cancelled_by=None,
        approval_key=None,
        approval_hash=None,
        cancel_key=None,
        cancel_hash=None,
        reason_code="TAXONOMY_CHANGE",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=2,
        payload=payload,
    )


def test_review_summary_exposes_allowlisted_category_fields_only() -> None:
    operation = _operation("CATEGORY_UPDATE", {
        "expected_version": 4,
        "command_payload": {
            "code": "HOME_GOODS",
            "slug": "home-goods",
            "name": "Home goods",
            "description": "Outdoor living and decor.",
            "image_media_id": "private-media-ref",
        },
    })

    review = _operation_review_response(operation, "request-123")

    assert review.approval_supported is True
    assert review.summary == {
        "code": "HOME_GOODS",
        "slug": "home-goods",
        "name": "Home goods",
        "description": "Outdoor living and decor.",
        "expected_version": 4,
    }
    assert "private-media-ref" not in str(review.model_dump())


def test_review_summary_fails_closed_for_unknown_operation_action() -> None:
    review = _operation_review_response(_operation("UNRECOGNIZED_ACTION", {"comment": "do not expose"}), "request-456")

    assert review.approval_supported is False
    assert review.summary == {}
    assert "do not expose" not in str(review.model_dump())


def test_review_summary_with_omitted_private_comment_cannot_be_approved() -> None:
    operation = _operation("SELLER_RESTRICTION", {
        "expected_version": 3,
        "command_payload": {
            "action": "SUSPEND",
            "effective_until": "2026-10-30T00:00:00Z",
            "comment": "restricted internal case detail",
        },
    })

    review = _operation_review_response(operation, "request-comment")

    assert review.approval_supported is False
    assert review.summary == {"action": "SUSPEND", "effective_until": "2026-10-30T00:00:00Z", "expected_version": 3}
    assert "restricted internal case detail" not in str(review.model_dump())


@pytest.mark.asyncio
async def test_unknown_operation_action_cannot_be_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    operation = _operation("UNRECOGNIZED_ACTION", {})
    database = SimpleNamespace(scalar=AsyncMock(return_value=operation))
    actor = SimpleNamespace(id=uuid4(), permissions={"operations.approve"}, permission_scopes={})
    monkeypatch.setattr(iam, "require_recent_step_up", lambda _actor: None)

    with pytest.raises(HTTPException) as error:
        await approve_operation(
            operation_id=operation.id,
            data=ReasonAction(reason_code=operation.reason_code),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-789")),
            idempotency_key=uuid4(),
            if_match='"2"',
            current=actor,
            db=database,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "OPERATION_ACTION_NOT_REVIEWABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "payload", "permission", "error_code"),
    [
        (
            "SELLER_RESTRICTION",
            {
                "expected_version": 1,
                "command_payload": {"action": "UNKNOWN", "reason_code": "TAXONOMY_CHANGE"},
            },
            "seller.restrict",
            "INVALID_SELLER_RESTRICTION",
        ),
        (
            "PRODUCT_SAFETY_HOLD",
            {
                "expected_version": 1,
                "command_payload": {"reason_code": "TAXONOMY_CHANGE", "expires_at": "not-a-date"},
                "hold_limit_seconds": 3600,
            },
            "products.safety_hold",
            "INVALID_SAFETY_HOLD",
        ),
        (
            "PRODUCT_SAFETY_HOLD",
            {
                "expected_version": 1,
                "command_payload": {"reason_code": "TAXONOMY_CHANGE", "expires_at": "not-a-date"},
                "hold_limit_seconds": "3600",
            },
            "products.safety_hold",
            "SAFETY_HOLD_POLICY_CHANGED",
        ),
    ],
)
async def test_approval_rejects_malformed_stored_external_command(
    action: str,
    payload: dict[str, object],
    permission: str,
    error_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation(action, payload)
    database = SimpleNamespace(scalar=AsyncMock(return_value=operation))
    scopes = {permission: {"*"}} if action == "SELLER_RESTRICTION" else {}
    actor = SimpleNamespace(id=uuid4(), permissions={permission}, permission_scopes=scopes)
    monkeypatch.setattr(iam, "require_recent_step_up", lambda _actor: None)
    monkeypatch.setattr(iam.settings, "admin_safety_hold_max_seconds", 3600)

    with pytest.raises(HTTPException) as error:
        await approve_operation(
            operation_id=operation.id,
            data=ReasonAction(reason_code=operation.reason_code),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-malformed-command")),
            idempotency_key=uuid4(),
            if_match='"2"',
            current=actor,
            db=database,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == error_code
