import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    require_permission,
    require_recent_step_up,
    staff_has_permission,
    verify_service_key,
)
from src.api.router import AdminAPIRoute
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.complaint import Complaint, ComplaintAction as ComplaintActionRow
from src.models.staff_principal import StaffPrincipal
from src.schemas.admin import AdminOperationResponse
from src.schemas.casework import ComplaintAction, ComplaintIntake, ComplaintView
from src.services.runtime_settings import effective_values
from src.schemas.admin_responses import (
    CaseTimelineEntry,
    ComplaintDetail,
    ComplaintEvidenceResponse,
    ComplaintPageResponse,
)

router = APIRouter(route_class=AdminAPIRoute, tags=["complaints"])


def _if_match(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        version = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IF_MATCH",
                "message": "If-Match must contain the complaint version",
            },
        ) from exc
    if version < 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IF_MATCH",
                "message": "If-Match version must be positive",
            },
        )
    return version


def _cursor(row: Complaint) -> str:
    value = json.dumps(
        {"v": 2, "p": row.priority, "t": row.created_at.isoformat(), "id": str(row.id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_cursor(value: str | None) -> tuple[int, datetime, UUID] | None:
    if value is None:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        if not isinstance(raw, dict):
            raise ValueError("cursor must be an object")
        version = raw.get("v")
        if isinstance(version, bool) or not isinstance(version, int) or version != 2:
            raise ValueError("unsupported complaint cursor version")
        priority = raw["p"]
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 1 <= priority <= 5
        ):
            raise ValueError("priority must be between 1 and 5")
        created_at = datetime.fromisoformat(raw["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return priority, created_at.astimezone(timezone.utc), UUID(raw["id"])
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
            detail={"code": "INVALID_CURSOR", "message": "Invalid complaint cursor"},
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


def _matches_intake(complaint: Complaint, data: ComplaintIntake) -> bool:
    return (
        complaint.source == data.source
        and complaint.reporter_ref == data.reporter_ref.lower()
        and complaint.entity_type == data.entity_type
        and complaint.entity_id == data.entity_id
        and complaint.category == data.category
        and complaint.priority == data.priority
        and complaint.evidence_refs == [ref.lower() for ref in data.evidence_refs]
    )


@router.post(
    "/internal/v1/complaints",
    status_code=202,
    dependencies=[Depends(verify_service_key)],
)
async def ingest_complaint(
    data: ComplaintIntake, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    for evidence_ref in data.evidence_refs:
        if len(evidence_ref) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in evidence_ref
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_EVIDENCE_REF",
                    "message": "Evidence references must be SHA-256 digests",
                },
            )
    existing = await db.scalar(
        select(Complaint).where(Complaint.source_event_id == data.event_id)
    )
    if existing is not None:
        if not _matches_intake(existing, data):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EVENT_ID_REUSED",
                    "message": "Event id was reused for different complaint content",
                },
            )
        return {"complaint_id": existing.id, "status": existing.status}
    now = datetime.now(timezone.utc)
    queue_settings, _ = await effective_values(db, "queue_policy")
    complaint = Complaint(
        source_event_id=data.event_id,
        source=data.source,
        reporter_ref=data.reporter_ref.lower(),
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        category=data.category,
        status="NEW",
        priority=data.priority,
        evidence_refs=[ref.lower() for ref in data.evidence_refs],
        version=1,
        created_at=now,
        deadline_at=now
        + timedelta(seconds=int(queue_settings["complaint_case_sla_seconds"])),
    )
    db.add(complaint)
    # Materialize the ORM UUID before creating its required audit row.
    await db.flush()
    db.add(
        AuditLog(
            actor_id=None,
            action="COMPLAINT_CREATED",
            entity_type="complaint",
            entity_id=complaint.id,
            details={
                "source": data.source,
                "entity_type": data.entity_type,
                "category": data.category,
            },
            created_at=now,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Complaint).where(Complaint.source_event_id == data.event_id)
        )
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMPLAINT_CONFLICT",
                    "message": "Complaint event conflicts with current state",
                },
            )
        if not _matches_intake(existing, data):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EVENT_ID_REUSED",
                    "message": "Event id was reused for different complaint content",
                },
            )
        complaint = existing
    return {"complaint_id": complaint.id, "status": complaint.status}


@router.get(
    "/admin/v1/complaints",
    response_model=ComplaintPageResponse,
    response_model_exclude_none=True,
)
async def list_complaints(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    current: SimpleNamespace = Depends(require_permission("complaint.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = _decode_cursor(cursor)
    query = select(Complaint)
    if position:
        priority, created_at, complaint_id = position
        query = query.where(
            (Complaint.priority < priority)
            | (
                (Complaint.priority == priority)
                & (
                    (Complaint.created_at > created_at)
                    | (
                        (Complaint.created_at == created_at)
                        & (Complaint.id > complaint_id)
                    )
                )
            )
        )
    if "complaint.read.unassigned" not in current.permissions:
        query = query.where(Complaint.assigned_to == current.id)
    rows = list(
        (
            await db.scalars(
                query.order_by(
                    Complaint.priority.desc(),
                    Complaint.created_at.asc(),
                    Complaint.id.asc(),
                ).limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    db.add(
        AuditLog(
            actor_id=current.id,
            action="COMPLAINT_LIST_READ",
            entity_type="complaint_collection",
            entity_id=current.id,
            details={"returned_count": len(rows), "has_more": has_more},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return {
        "items": [
            ComplaintView.model_validate(row).model_dump(mode="json") for row in rows
        ],
        "page": {
            "has_more": has_more,
            "next_cursor": _cursor(rows[-1]) if has_more and rows else None,
        },
    }


@router.get(
    "/admin/v1/complaints/{complaint_id}",
    response_model=ComplaintDetail,
    response_model_exclude_none=True,
    summary="Read complaint details and case timeline",
)
async def get_complaint(
    complaint_id: UUID,
    request: Request,
    response: Response,
    current: SimpleNamespace = Depends(require_permission("complaint.read")),
    db: AsyncSession = Depends(get_db),
) -> ComplaintDetail:
    row = await db.get(Complaint, complaint_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    if (
        "complaint.read.unassigned" not in current.permissions
        and row.assigned_to != current.id
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    response.headers["ETag"] = f'"{row.version}"'
    db.add(
        AuditLog(
            actor_id=current.id,
            action="COMPLAINT_READ",
            entity_type="complaint",
            entity_id=row.id,
            details={"request_id": getattr(request.state, "request_id", None)},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    audit_rows = (
        await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "complaint",
                AuditLog.entity_id == row.id,
                AuditLog.action.in_(
                    (
                        "COMPLAINT_CREATED",
                        "COMPLAINT_ASSIGN",
                        "COMPLAINT_REQUEST_INFO",
                        "COMPLAINT_WARN",
                        "COMPLAINT_TEMP_HOLD",
                        "COMPLAINT_UNPUBLISH",
                        "COMPLAINT_CLOSE",
                        "COMPLAINT_ESCALATE",
                        "COMPLAINT_ACTION_APPROVED",
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
                assigned_to=UUID(details["assigned_to"])
                if isinstance(details.get("assigned_to"), str)
                else None,
            )
        )
    return ComplaintDetail(
        **ComplaintView.model_validate(row).model_dump(),
        timeline=timeline,
    )


@router.get(
    "/admin/v1/complaints/{complaint_id}/evidence",
    response_model=ComplaintEvidenceResponse,
    response_model_exclude_none=True,
    operation_id="GET_admin_v1_complaints_complaint_id_evidence",
    summary="Read complaint evidence references",
)
async def get_complaint_evidence(
    complaint_id: UUID,
    request: Request,
    current: SimpleNamespace = Depends(require_permission("complaint.evidence.read")),
    db: AsyncSession = Depends(get_db),
) -> ComplaintEvidenceResponse:
    row = await db.get(Complaint, complaint_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    if (
        "complaint.read.unassigned" not in current.permissions
        and row.assigned_to != current.id
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    db.add(
        AuditLog(
            actor_id=current.id,
            action="COMPLAINT_EVIDENCE_READ",
            entity_type="complaint",
            entity_id=row.id,
            details={
                "request_id": getattr(request.state, "request_id", None),
                "evidence_count": len(row.evidence_refs),
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return ComplaintEvidenceResponse(
        complaint_id=row.id,
        evidence_refs=row.evidence_refs,
        scan_status="NOT_CONFIGURED",
    )


@router.post(
    "/admin/v1/complaints/{complaint_id}/actions",
    response_model=AdminOperationResponse,
    status_code=202,
)
async def complaint_action(
    complaint_id: UUID,
    data: ComplaintAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(require_permission("complaint.decide")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    if data.action in {"REQUEST_INFO", "WARN", "CLOSE"}:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "NOTICE_DELIVERY_NOT_CONFIGURED",
                "message": "This action requires a configured case-notice delivery service",
            },
        )
    elevated = data.action in {"TEMP_HOLD", "UNPUBLISH"}
    if elevated:
        require_recent_step_up(current)
    expected_version = _if_match(if_match)
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(
            {
                "complaint_id": str(complaint_id),
                "version": expected_version,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    previous = await db.scalar(
        select(ComplaintActionRow).where(
            ComplaintActionRow.actor_id == current.id,
            ComplaintActionRow.idempotency_key == str(idempotency_key),
        )
    )
    if previous is not None:
        if previous.complaint_id != complaint_id or not hmac.compare_digest(
            previous.request_hash, request_hash
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "Idempotency key was used for a different complaint action",
                },
            )
        operation = await db.scalar(
            select(AdminOperation).where(AdminOperation.id == previous.id)
        )
        if operation is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACTION_RECEIPT_INCOMPLETE",
                    "message": "Complaint action receipt is incomplete",
                },
            )
        return _operation(operation, request)
    complaint = await db.scalar(
        select(Complaint).where(Complaint.id == complaint_id).with_for_update()
    )
    if complaint is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    if complaint.version != expected_version:
        raise HTTPException(
            status_code=412,
            detail={
                "code": "VERSION_MISMATCH",
                "message": "Complaint changed; reload before acting",
            },
        )
    if complaint.status == "CLOSED":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPLAINT_CLOSED",
                "message": "Closed complaints cannot be changed",
            },
        )
    if data.action == "ASSIGN":
        if complaint.status != "NEW":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMPLAINT_NOT_ASSIGNABLE",
                    "message": "Only new complaints can be assigned",
                },
            )
        if complaint.assigned_to is not None:
            if complaint.assigned_to == current.id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "COMPLAINT_ALREADY_ASSIGNED",
                        "message": "Complaint is already assigned to this reviewer",
                    },
                )
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "COMPLAINT_NOT_FOUND",
                    "message": "Complaint not found",
                },
            )
        assignee_id = data.assignee_staff_id or current.id
        assignee = await db.scalar(
            select(StaffPrincipal)
            .where(StaffPrincipal.id == assignee_id)
            .with_for_update()
        )
        if assignee is None or not await staff_has_permission(
            assignee, "complaint.read", db
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ASSIGNEE_NOT_ELIGIBLE",
                    "message": "Assignee must be an active staff member with complaint read access",
                },
            )
    elif data.assignee_staff_id is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ASSIGNEE_ONLY_FOR_ASSIGN",
                "message": "assignee_staff_id is only valid for ASSIGN",
            },
        )
    elif complaint.assigned_to != current.id:
        if complaint.assigned_to is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMPLAINT_ASSIGNMENT_REQUIRED",
                    "message": "Assign the complaint before acting on it",
                },
            )
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint not found"},
        )
    now = datetime.now(timezone.utc)
    operation_id = uuid4()
    operation = AdminOperation(
        id=operation_id,
        action="COMPLAINT_ACTION",
        entity_type="complaint",
        entity_id=complaint.id,
        payload={**payload, "expected_version": expected_version},
        status="WAITING_APPROVAL" if elevated else "APPLIED",
        version=1,
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        requested_by=current.id,
        reason_code=data.reason_code,
        updated_at=now,
    )
    db.add(operation)
    db.add(
        ComplaintActionRow(
            id=operation_id,
            complaint_id=complaint.id,
            actor_id=current.id,
            action=data.action,
            reason_code=data.reason_code,
            comment=data.comment,
            idempotency_key=str(idempotency_key),
            request_hash=request_hash,
        )
    )
    if not elevated:
        if data.action == "ASSIGN":
            complaint.assigned_to, complaint.status = assignee_id, "TRIAGED"
        elif data.action == "CLOSE":
            complaint.status = "CLOSED"
        elif data.action == "ESCALATE":
            complaint.status = "ESCALATED"
        elif complaint.status == "NEW":
            complaint.status = (
                "IN_REVIEW" if data.action in {"REQUEST_INFO", "WARN"} else "TRIAGED"
            )
        complaint.version += 1
        complaint.updated_at = now
    db.add(
        AuditLog(
            actor_id=current.id,
            action=f"COMPLAINT_{data.action}",
            entity_type="complaint",
            entity_id=complaint.id,
            details={
                "operation_id": str(operation_id),
                "reason_code": data.reason_code,
                "approval_required": elevated,
                **(
                    {"assigned_to": str(assignee_id)} if data.action == "ASSIGN" else {}
                ),
            },
            created_at=now,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPLAINT_ACTION_CONFLICT",
                "message": "Complaint action conflicts with another request",
            },
        ) from exc
    return _operation(operation, request)
