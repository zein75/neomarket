import csv
import hashlib
import hmac
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.core.config import settings
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_chain_head import AuditChainHead
from src.models.audit_export import AuditExportArtifact
from src.models.audit_log import AuditLog
from src.schemas.admin import AdminOperationResponse, AuditExportInput


router = APIRouter(route_class=AdminAPIRoute, tags=["audit-events"])
_MAX_EXPORT_EVENTS = 25_000


def _request_hash(data: AuditExportInput) -> str:
    body = data.model_dump(mode="json")
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _operation_response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=str(request.state.request_id),
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _archive_export(
    *, artifact_id: UUID, actor_id: UUID, data: AuditExportInput,
    high_water_sequence: int, high_water_hash: str, events: list[AuditLog], created_at: datetime,
) -> bytes:
    event_file = io.StringIO(newline="")
    fields = (
        "sequence_no", "id", "actor_id", "action", "entity_type", "entity_id",
        "created_at", "request_id", "correlation_id", "actor_roles", "before_hash",
        "after_hash", "reason_code", "integrity_version", "details", "previous_hash", "integrity_hash",
    )
    writer = csv.DictWriter(event_file, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for event in events:
        writer.writerow({
            "sequence_no": event.sequence_no,
            "id": event.id,
            "actor_id": event.actor_id,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "created_at": event.created_at.astimezone(timezone.utc).isoformat(),
            "request_id": event.request_id,
            "correlation_id": event.correlation_id,
            "actor_roles": json.dumps(event.actor_roles, separators=(",", ":")) if event.actor_roles is not None else "",
            "before_hash": event.before_hash,
            "after_hash": event.after_hash,
            "reason_code": event.reason_code,
            "integrity_version": event.integrity_version,
            # Audit details can contain personal or confidential values. The export
            # intentionally keeps the immutable event envelope and chain hashes only.
            "details": "[REDACTED]",
            "previous_hash": event.previous_hash,
            "integrity_hash": event.integrity_hash,
        })
    manifest = {
        "format": "neomarket-admin-audit-export-v3",
        "export_id": str(artifact_id),
        "requested_by": str(actor_id),
        "created_at": created_at.isoformat(),
        "start_at": data.start_at.astimezone(timezone.utc).isoformat(),
        "end_at": data.end_at.astimezone(timezone.utc).isoformat(),
        "reason_code": data.reason_code,
        "row_count": len(events),
        "event_details": "omitted_for_data_minimization",
        "chain_hashes_cover": "original_events_in_canonical_audit_store",
        "high_water_sequence": high_water_sequence,
        "high_water_hash": high_water_hash,
        "chain_note": "The high-water mark is captured before the export audit event is appended.",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False))
        archive.writestr("events.csv", event_file.getvalue())
    return output.getvalue()


@router.post(
    "/admin/v1/audit-events/export",
    response_model=AdminOperationResponse,
    status_code=202,
    operation_id="POST_admin_v1_audit_events_export",
)
async def request_audit_export(
    data: AuditExportInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("audit.export")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    start_at = data.start_at.astimezone(timezone.utc)
    end_at = data.end_at.astimezone(timezone.utc)
    if end_at <= start_at:
        raise HTTPException(status_code=422, detail={"code": "INVALID_EXPORT_RANGE", "message": "end_at must be later than start_at"})
    request_hash = _request_hash(data)
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "AUDIT_EXPORT" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        artifact = await db.get(AuditExportArtifact, prior.entity_id)
        if artifact is None or artifact.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail={"code": "AUDIT_EXPORT_EXPIRED", "message": "This idempotent export has expired; submit a new request with a new key"})
        return _operation_response(prior, request)

    # Lock the chain head so the export range and its high-water mark describe
    # one stable append-only audit prefix while the archive is assembled.
    head = await db.scalar(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update())
    if head is None:
        raise HTTPException(status_code=503, detail={"code": "AUDIT_CHAIN_UNAVAILABLE", "message": "Audit integrity chain is not initialized"})
    events = list((await db.scalars(
        select(AuditLog)
        .where(AuditLog.created_at >= start_at, AuditLog.created_at < end_at)
        .order_by(AuditLog.sequence_no.asc())
        .limit(_MAX_EXPORT_EVENTS + 1)
    )).all())
    if len(events) > _MAX_EXPORT_EVENTS:
        raise HTTPException(status_code=422, detail={"code": "AUDIT_EXPORT_TOO_LARGE", "message": "Narrow the time range; exports are limited to 25,000 events"})

    now = datetime.now(timezone.utc)
    export_id = uuid4()
    expires_at = now + timedelta(seconds=settings.audit_export_ttl_seconds)
    content = _archive_export(
        artifact_id=export_id, actor_id=actor.id, data=data,
        high_water_sequence=head.last_sequence, high_water_hash=head.last_hash,
        events=events, created_at=now,
    )
    digest = hashlib.sha256(content).hexdigest()
    operation = AdminOperation(
        id=uuid4(), action="AUDIT_EXPORT", entity_type="audit_export", entity_id=export_id,
        payload={"sha256": digest, "row_count": len(events), "expires_at": expires_at.isoformat()},
        status="APPLIED", version=1, idempotency_key=str(idempotency_key),
        request_hash=request_hash, requested_by=actor.id, reason_code=data.reason_code,
        updated_at=now,
    )
    artifact = AuditExportArtifact(
        id=export_id, requested_by=actor.id, created_at=now, expires_at=expires_at,
        start_at=start_at, end_at=end_at, row_count=len(events),
        high_water_sequence=head.last_sequence, high_water_hash=head.last_hash,
        sha256=digest, content=content,
    )
    db.add_all([
        artifact,
        operation,
        AuditLog(
            actor_id=actor.id, action="AUDIT_EXPORT_CREATED", entity_type="audit_export",
            entity_id=export_id,
            details={"sha256": digest, "row_count": len(events), "start_at": start_at.isoformat(),
                     "end_at": end_at.isoformat(), "reason_code": data.reason_code,
                     "expires_at": expires_at.isoformat(), "high_water_sequence": head.last_sequence},
            created_at=now,
        ),
    ])
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if prior is not None and prior.action == "AUDIT_EXPORT" and hmac.compare_digest(prior.request_hash, request_hash):
            return _operation_response(prior, request)
        raise HTTPException(status_code=409, detail={"code": "AUDIT_EXPORT_CONFLICT", "message": "Audit export could not be recorded"}) from exc
    return _operation_response(operation, request)


@router.get("/admin/v1/audit-events/exports/{export_id}", operation_id="GET_admin_v1_audit_events_exports_export_id")
async def download_audit_export(
    export_id: UUID,
    request: Request,
    actor: SimpleNamespace = Depends(require_permission("audit.export")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    artifact = await db.scalar(select(AuditExportArtifact).where(
        AuditExportArtifact.id == export_id,
        AuditExportArtifact.requested_by == actor.id,
    ))
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "AUDIT_EXPORT_NOT_FOUND", "message": "Audit export not found"})
    if artifact.expires_at <= datetime.now(timezone.utc):
        await db.delete(artifact)
        await db.commit()
        raise HTTPException(status_code=410, detail={"code": "AUDIT_EXPORT_EXPIRED", "message": "Audit export has expired"})
    if not hmac.compare_digest(hashlib.sha256(artifact.content).hexdigest(), artifact.sha256):
        db.add(AuditLog(
            actor_id=actor.id, action="AUDIT_EXPORT_INTEGRITY_FAILED", entity_type="audit_export",
            entity_id=artifact.id, details={"expected_sha256": artifact.sha256},
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        raise HTTPException(status_code=503, detail={"code": "AUDIT_EXPORT_INTEGRITY_FAILED", "message": "Stored audit export failed its integrity check"})
    db.add(AuditLog(
        actor_id=actor.id, action="AUDIT_EXPORT_DOWNLOADED", entity_type="audit_export",
        entity_id=artifact.id, details={"sha256": artifact.sha256}, created_at=datetime.now(timezone.utc),
    ))
    content = bytes(artifact.content)
    digest = artifact.sha256
    await db.commit()
    filename = f"neomarket-audit-{artifact.id}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "X-Content-SHA256": digest,
            "Cache-Control": "no-store",
        },
    )
