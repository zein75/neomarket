from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.admin_policy import AdminPolicy

RuntimeSection = Literal["queue_policy", "workflow_settings"]

POLICY_CODES: dict[str, str] = {
    "queue_policy": "ADMIN_QUEUE_POLICY",
    "workflow_settings": "ADMIN_WORKFLOW_SETTINGS",
}
SECTIONS_BY_POLICY_CODE = {code: section for section, code in POLICY_CODES.items()}

_FIELDS: dict[str, frozenset[str]] = {
    "queue_policy": frozenset({
        "moderation_claim_ttl_seconds",
        "complaint_case_sla_seconds",
    }),
    "workflow_settings": frozenset({
        "admin_session_idle_ttl_seconds",
        "admin_session_absolute_ttl_seconds",
        "admin_step_up_max_age_seconds",
        "moderation_outbox_poll_interval_seconds",
    }),
}


def validate_values(section: RuntimeSection, values: object) -> dict[str, int | float]:
    if not isinstance(values, dict) or set(values) != _FIELDS[section]:
        raise ValueError("Runtime policy must contain exactly the supported settings for its section")
    if section == "queue_policy":
        if any(type(values[key]) is not int or values[key] < 1 for key in _FIELDS[section]):
            raise ValueError("Queue policy values must be positive integers")
        return dict(values)

    integer_fields = {
        "admin_session_idle_ttl_seconds",
        "admin_session_absolute_ttl_seconds",
        "admin_step_up_max_age_seconds",
    }
    if any(type(values[key]) is not int for key in integer_fields):
        raise ValueError("Workflow durations must be integers")
    idle = values["admin_session_idle_ttl_seconds"]
    absolute = values["admin_session_absolute_ttl_seconds"]
    step_up = values["admin_step_up_max_age_seconds"]
    interval = values["moderation_outbox_poll_interval_seconds"]
    if not 300 <= idle <= 86400:
        raise ValueError("ADMIN_SESSION_IDLE_TTL_SECONDS must be between 300 and 86400")
    if not idle <= absolute <= 604800:
        raise ValueError("ADMIN_SESSION_ABSOLUTE_TTL_SECONDS must be between idle TTL and 604800")
    if not 60 <= step_up <= 1800:
        raise ValueError("ADMIN_STEP_UP_MAX_AGE_SECONDS must be between 60 and 1800")
    if type(interval) not in {int, float} or not 0.1 <= interval <= 300:
        raise ValueError("MODERATION_OUTBOX_POLL_INTERVAL_SECONDS must be between 0.1 and 300")
    return dict(values)


def validate_policy_rules(code: str, rules: object) -> tuple[RuntimeSection, dict[str, int | float], int] | None:
    section = SECTIONS_BY_POLICY_CODE.get(code)
    if section is None:
        return None
    if not isinstance(rules, dict):
        raise ValueError("Runtime policy rules must be an object")
    expected_version = rules.get("expected_current_version")
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("Runtime policy must carry a non-negative expected current version")
    values = validate_values(section, rules.get("values"))
    return section, values, expected_version


def environment_values(section: RuntimeSection) -> dict[str, int | float]:
    if section == "queue_policy":
        return {
            "moderation_claim_ttl_seconds": settings.moderation_claim_ttl_seconds,
            "complaint_case_sla_seconds": settings.complaint_case_sla_seconds,
        }
    return {
        "admin_session_idle_ttl_seconds": settings.admin_session_idle_ttl_seconds,
        "admin_session_absolute_ttl_seconds": settings.admin_session_absolute_ttl_seconds,
        "admin_step_up_max_age_seconds": settings.admin_step_up_max_age_seconds,
        "moderation_outbox_poll_interval_seconds": settings.moderation_outbox_poll_interval_seconds,
    }


async def active_policy(db: AsyncSession, section: RuntimeSection) -> AdminPolicy | None:
    return await db.scalar(
        select(AdminPolicy)
        .where(
            AdminPolicy.code == POLICY_CODES[section],
            AdminPolicy.status == "PUBLISHED",
        )
        .order_by(AdminPolicy.version.desc(), AdminPolicy.id.desc())
        .limit(1)
    )


async def active_version(db: AsyncSession, section: RuntimeSection) -> int:
    policy = await active_policy(db, section)
    return policy.version if policy is not None else 0


async def effective_values(db: AsyncSession, section: RuntimeSection) -> tuple[dict[str, int | float], int | None]:
    policy = await active_policy(db, section)
    if policy is None:
        try:
            return validate_values(section, environment_values(section)), None
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "RUNTIME_POLICY_INVALID", "message": "Environment runtime settings are invalid"},
            ) from exc
    rules = policy.rules
    try:
        values = validate_values(section, rules.get("values") if isinstance(rules, dict) else None)
    except (AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "RUNTIME_POLICY_INVALID", "message": "Published runtime policy is invalid; configuration remains unavailable"},
        ) from exc
    return values, policy.version
