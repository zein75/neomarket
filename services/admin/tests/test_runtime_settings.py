from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.routers import integrations
from src.models.admin_operation import AdminOperation
from src.services.runtime_settings import effective_values, validate_policy_rules, validate_values
from src.schemas.admin import RuntimeSettingsProposalInput


class FakeSession:
    def __init__(self, active_policy=None, prior_operation=None):
        self.active_policy = active_policy
        self.prior_operation = prior_operation
        self.added = []
        self.commits = 0

    async def scalar(self, statement):
        return self.prior_operation if "admin_operations" in str(statement) else self.active_policy

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


def _request():
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/admin/v1/settings/queue_policy/versions",
        "raw_path": b"/admin/v1/settings/queue_policy/versions",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 443),
        "path_params": {},
        "state": {"request_id": "req-test"},
        "app": None,
    })


def _queue_values():
    return {
        "moderation_claim_ttl_seconds": 900,
        "complaint_case_sla_seconds": 86400,
    }


def test_runtime_policy_requires_exact_supported_fields_and_safe_ranges():
    assert validate_values("queue_policy", _queue_values()) == _queue_values()
    with pytest.raises(ValueError):
        validate_values("queue_policy", {**_queue_values(), "retention_days": 30})
    with pytest.raises(ValueError):
        validate_values("workflow_settings", {
            "admin_session_idle_ttl_seconds": 3600,
            "admin_session_absolute_ttl_seconds": 1800,
            "admin_step_up_max_age_seconds": 300,
            "moderation_outbox_poll_interval_seconds": 1.0,
        })


def test_reserved_policy_requires_optimistic_base_version():
    with pytest.raises(ValueError):
        validate_policy_rules("ADMIN_QUEUE_POLICY", {"values": _queue_values()})
    assert validate_policy_rules("UNRELATED_POLICY", {}) is None


@pytest.mark.asyncio
async def test_effective_settings_use_published_version_not_environment_fallback():
    policy = SimpleNamespace(
        rules={"values": _queue_values(), "expected_current_version": 0},
        version=5,
    )
    values, version = await effective_values(FakeSession(active_policy=policy), "queue_policy")

    assert values == _queue_values()
    assert version == 5


@pytest.mark.asyncio
async def test_queue_policy_proposal_uses_existing_independent_policy_approval_flow():
    db = FakeSession()
    actor = SimpleNamespace(id=uuid4())
    response = await integrations.propose_runtime_settings(
        "queue_policy",
        RuntimeSettingsProposalInput(
            expected_version=0,
            values=_queue_values(),
            reason_code="QUEUE_POLICY_CHANGE",
        ),
        _request(),
        uuid4(),
        actor,
        db,
    )

    operation = next(item for item in db.added if isinstance(item, AdminOperation))
    assert response.status == "WAITING_APPROVAL"
    assert response.resource_id == operation.entity_id
    assert operation.action == "POLICY_CREATE"
    assert operation.payload["code"] == "ADMIN_QUEUE_POLICY"
    assert operation.payload["rules"]["values"] == _queue_values()
    assert operation.payload["rules"]["expected_current_version"] == 0
    assert operation.payload["expected_current_version"] == 0
    assert len(operation.payload["content_hash"]) == 64
    assert db.commits == 1


@pytest.mark.asyncio
async def test_stale_runtime_policy_base_is_rejected_before_proposal():
    db = FakeSession(active_policy=SimpleNamespace(version=4))
    with pytest.raises(HTTPException) as error:
        await integrations.propose_runtime_settings(
            "queue_policy",
            RuntimeSettingsProposalInput(
                expected_version=3,
                values=_queue_values(),
                reason_code="QUEUE_POLICY_CHANGE",
            ),
            _request(),
            uuid4(),
            SimpleNamespace(id=uuid4()),
            db,
        )

    assert error.value.status_code == 412
    assert error.value.detail["code"] == "RUNTIME_POLICY_VERSION_MISMATCH"
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_after_active_version_advances():
    idempotency_key = uuid4()
    actor = SimpleNamespace(id=uuid4())
    data = RuntimeSettingsProposalInput(
        expected_version=0,
        values=_queue_values(),
        reason_code="QUEUE_POLICY_CHANGE",
    )
    first_db = FakeSession()
    first = await integrations.propose_runtime_settings(
        "queue_policy", data, _request(), idempotency_key, actor, first_db
    )
    operation = next(item for item in first_db.added if isinstance(item, AdminOperation))

    replay_db = FakeSession(
        active_policy=SimpleNamespace(version=1),
        prior_operation=operation,
    )
    replay = await integrations.propose_runtime_settings(
        "queue_policy", data, _request(), idempotency_key, actor, replay_db
    )

    assert replay.operation_id == first.operation_id
    assert replay.resource_id == first.resource_id
    assert replay_db.commits == 0
