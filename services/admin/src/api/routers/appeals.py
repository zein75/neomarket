import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission, verify_service_key
from src.api.router import AdminAPIRoute
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.appeal import Appeal
from src.models.audit_log import AuditLog
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.schemas.admin import AdminOperationResponse
from src.schemas.appeals import AppealAction, AppealIntake, AppealView
from src.schemas.admin_responses import (
    AppealDetail,
    AppealEvidenceResponse,
    AppealPageResponse,
    CaseTimelineEntry,
    OriginalDecisionResponse,
)

router = APIRouter(route_class=AdminAPIRoute, tags=["appeals"])


def _if_match(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        result = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IF_MATCH",
                "message": "If-Match must contain the appeal version",
            },
        ) from exc
    if result < 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IF_MATCH",
                "message": "If-Match version must be positive",
            },
        )
    return result


def _cursor(row: Appeal) -> str:
    value = json.dumps(
        {"t": row.created_at.isoformat(), "id": str(row.id)}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        created_at = datetime.fromisoformat(raw["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return created_at.astimezone(timezone.utc), UUID(raw["id"])
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        base64.binascii.Error,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURSOR", "message": "Invalid appeal cursor"},
        ) from exc


def _operation(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


@router.post(
    "/internal/v1/appeals", status_code=202, dependencies=[Depends(verify_service_key)]
)
async def ingest_appeal(
    data: AppealIntake, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    if any(
        len(ref) != 64 or any(char not in "0123456789abcdefABCDEF" for char in ref)
        for ref in data.evidence_refs
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_EVIDENCE_REF",
                "message": "Evidence references must be SHA-256 digests",
            },
        )
    previous = await db.scalar(
        select(Appeal).where(Appeal.source_event_id == data.event_id)
    )
    if previous is not None:
        if (
            previous.original_decision_id != data.original_decision_id
            or previous.claimant_ref != data.claimant_ref.lower()
            or previous.evidence_refs != [ref.lower() for ref in data.evidence_refs]
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EVENT_ID_REUSED",
                    "message": "Appeal event id was reused for different content",
                },
            )
        return {"appeal_id": previous.id, "status": previous.status}
    decision = await db.get(ModerationDecisionReceipt, data.original_decision_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DECISION_NOT_FOUND",
                "message": "Original decision not found",
            },
        )
    appeal = Appeal(
        source_event_id=data.event_id,
        original_decision_id=data.original_decision_id,
        claimant_ref=data.claimant_ref.lower(),
        evidence_refs=[ref.lower() for ref in data.evidence_refs],
        status="SUBMITTED",
        version=1,
    )
    db.add(appeal)
    # Materialize the ORM UUID before creating its required audit row.
    await db.flush()
    db.add(
        AuditLog(
            actor_id=None,
            action="APPEAL_SUBMITTED",
            entity_type="appeal",
            entity_id=appeal.id,
            details={"original_decision_id": str(data.original_decision_id)},
            created_at=datetime.now(timezone.utc),
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        previous = await db.scalar(
            select(Appeal).where(Appeal.source_event_id == data.event_id)
        )
        if previous is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "APPEAL_CONFLICT",
                    "message": "Appeal event conflicts with current state",
                },
            ) from exc
        if (
            previous.original_decision_id != data.original_decision_id
            or previous.claimant_ref != data.claimant_ref.lower()
            or previous.evidence_refs != [ref.lower() for ref in data.evidence_refs]
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EVENT_ID_REUSED",
                    "message": "Appeal event id was reused for different content",
                },
            )
        appeal = previous
    return {"appeal_id": appeal.id, "status": appeal.status}


@router.get(
    "/admin/v1/appeals",
    response_model=AppealPageResponse,
    response_model_exclude_none=True,
)
async def list_appeals(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    actor: SimpleNamespace = Depends(require_permission("appeal.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = _decode_cursor(cursor)
    query = select(Appeal)
    if position:
        created_at, appeal_id = position
        query = query.where(
            (Appeal.created_at < created_at)
            | ((Appeal.created_at == created_at) & (Appeal.id < appeal_id))
        )
    rows = list(
        (
            await db.scalars(
                query.order_by(Appeal.created_at.desc(), Appeal.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    db.add(
        AuditLog(
            actor_id=actor.id,
            action="APPEAL_LIST_READ",
            entity_type="appeal_collection",
            entity_id=actor.id,
            details={"returned_count": len(rows), "has_more": has_more},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return {
        "items": [
            AppealView.model_validate(row).model_dump(mode="json") for row in rows
        ],
        "page": {
            "has_more": has_more,
            "next_cursor": _cursor(rows[-1]) if has_more and rows else None,
        },
    }


@router.get(
    "/admin/v1/appeals/{appeal_id}",
    response_model=AppealDetail,
    response_model_exclude_none=True,
)
async def get_appeal(
    appeal_id: UUID,
    request: Request,
    current: SimpleNamespace = Depends(require_permission("appeal.read")),
    db: AsyncSession = Depends(get_db),
) -> AppealDetail:
    appeal = await db.get(Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "APPEAL_NOT_FOUND", "message": "Appeal not found"},
        )
    original = await db.get(ModerationDecisionReceipt, appeal.original_decision_id)
    if original is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ORIGINAL_DECISION_MISSING",
                "message": "Original decision cannot be verified",
            },
        )
    db.add(
        AuditLog(
            actor_id=current.id,
            action="APPEAL_READ",
            entity_type="appeal",
            entity_id=appeal.id,
            details={"request_id": getattr(request.state, "request_id", None)},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    audit_rows = (
        await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "appeal",
                AuditLog.entity_id == appeal.id,
                AuditLog.action.in_(
                    (
                        "APPEAL_SUBMITTED",
                        "APPEAL_DECISION_PROPOSED",
                        "APPEAL_DECISION_APPROVED",
                    )
                ),
            )
            .order_by(AuditLog.created_at, AuditLog.sequence_no)
        )
    ).all()
    timeline = []
    for event in audit_rows:
        details = event.details if isinstance(event.details, dict) else {}
        timeline.append(
            CaseTimelineEntry(
                event_id=event.id,
                action=event.action,
                actor_id=event.actor_id,
                occurred_at=event.created_at,
                reason_code=event.reason_code,
                operation_id=UUID(details["operation_id"])
                if isinstance(details.get("operation_id"), str)
                else None,
                outcome=details.get("outcome")
                if isinstance(details.get("outcome"), str)
                else None,
            )
        )
    return AppealDetail(
        **AppealView.model_validate(appeal).model_dump(),
        timeline=timeline,
        original_decision=OriginalDecisionResponse(
            decision_id=original.id,
            ticket_id=original.ticket_id,
            actor_id=original.actor_id,
            action=original.action,
            product_revision=original.product_revision,
            snapshot_hash=original.snapshot_hash,
            policy_version=original.policy_version,
            reason_codes=original.reason_codes,
            passed_rules=original.passed_rules,
            decided_at=original.created_at,
        ),
    )


@router.get(
    "/admin/v1/appeals/{appeal_id}/evidence",
    response_model=AppealEvidenceResponse,
    response_model_exclude_none=True,
    operation_id="GET_admin_v1_appeals_appeal_id_evidence",
    summary="Read appeal evidence references",
)
async def get_appeal_evidence(
    appeal_id: UUID,
    request: Request,
    current: SimpleNamespace = Depends(require_permission("appeal.evidence.read")),
    db: AsyncSession = Depends(get_db),
) -> AppealEvidenceResponse:
    appeal = await db.get(Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "APPEAL_NOT_FOUND", "message": "Appeal not found"},
        )
    db.add(
        AuditLog(
            actor_id=current.id,
            action="APPEAL_EVIDENCE_READ",
            entity_type="appeal",
            entity_id=appeal.id,
            details={
                "request_id": getattr(request.state, "request_id", None),
                "evidence_count": len(appeal.evidence_refs),
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return AppealEvidenceResponse(
        appeal_id=appeal.id,
        evidence_refs=appeal.evidence_refs,
        scan_status="NOT_CONFIGURED",
    )


@router.post(
    "/admin/v1/appeals/{appeal_id}/decisions",
    response_model=AdminOperationResponse,
    status_code=202,
)
async def propose_appeal_decision(
    appeal_id: UUID,
    data: AppealAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(require_permission("appeal.decide")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    appeal = await db.get(Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "APPEAL_NOT_FOUND", "message": "Appeal not found"},
        )
    original = await db.get(ModerationDecisionReceipt, appeal.original_decision_id)
    if original is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "APPEAL_ORIGINAL_DECISION_UNAVAILABLE",
                "message": "The original decision required for independent review is unavailable",
            },
        )
    if original.actor_id == current.id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "APPEAL_REVIEWER_NOT_INDEPENDENT",
                "message": "The original decision actor cannot decide its appeal",
            },
        )
    raise HTTPException(
        status_code=503,
        detail={
            "code": "NOTICE_DELIVERY_NOT_CONFIGURED",
            "message": "Appeal decisions require a configured case-notice delivery service",
        },
    )
