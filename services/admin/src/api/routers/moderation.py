import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import _record_access_denial, authorize_permission_scope, require_permission, require_recent_step_up, verify_service_key
from src.api.router import AdminAPIRoute
from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.core.database import get_db
from src.schemas.moderation import (
    BlockDecisionRequest,
    BlockingReasonResponse,
    AuditPage,
    ModerationCardResponse,
    ProductEventRequest,
    TicketResponse,
    DecisionInput,
    DecisionResult,
    ClaimResult,
    LeaseInput,
    ProductEventEnvelope,
    PublicationDecisionEnvelope,
)
from src.schemas.admin_responses import DashboardMetricsResponse, ProductSnapshotResponse, TicketDetailResponse, TicketPageResponse
from src.schemas.products import ProductPublication, ProductRevisionSnapshot
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.models.complaint import Complaint
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_snapshot import ModerationSnapshot
from src.services.moderation_service import ModerationService
from src.services.product_snapshots import normalize_source_digest


router = APIRouter(route_class=AdminAPIRoute, tags=["moderation"])


def _snapshot_field_diff(before: dict[str, object], after: dict[str, object]) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    missing = object()

    def visit(path: str, old: object, new: object) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                visit(f"{path}.{key}" if path else key, old.get(key, missing), new.get(key, missing))
        elif old != new:
            changes.append({"path": path, "before": None if old is missing else old, "after": None if new is missing else new})

    visit("", before, after)
    return changes


def _reviewable_snapshot_fields(snapshot: ProductSnapshotResponse) -> dict[str, object]:
    return snapshot.model_dump(
        mode="json",
        include={"title", "description", "category_id", "images", "skus", "attributes", "policy_version"},
    )


def _ticket_response(card: object) -> TicketResponse:
    try:
        return TicketResponse.model_validate(card)
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "REVALIDATION_REQUIRED", "message": "Ticket lacks the revision-bound fields required by the Admin contract"},
        ) from exc


def _review_checklist(snapshot: ProductSnapshotResponse, *, revision_pinned: bool, published_loaded: bool) -> list[dict[str, object]]:
    """Expose the reviewable product checks from the immutable source snapshot."""
    title_present = isinstance(snapshot.title, str) and bool(snapshot.title.strip())
    category_present = snapshot.category_id is not None
    sku_present = bool(snapshot.skus)
    sku_prices_valid = all(
        sku.price_minor is not None and sku.price_minor >= 0 and isinstance(sku.currency, str) and bool(sku.currency.strip())
        for sku in snapshot.skus
    )
    media_refs_valid = bool(snapshot.images) and all(
        image.url is not None and str(image.url).strip() for image in snapshot.images
    ) and all(
        image.url is not None and str(image.url).strip()
        for sku in snapshot.skus
        for image in sku.images
    )
    return [
        {"code": "SNAPSHOT_HASH", "passed": True, "message": "Pinned snapshot hash verified"},
        {"code": "REVISION_PINNED", "passed": revision_pinned, "message": "Ticket revision is pinned"},
        {"code": "PUBLISHED_REVISION", "passed": True, "message": "Published baseline loaded" if published_loaded else "Product has no published revision"},
        {"code": "TITLE_RULES", "passed": title_present, "message": "Product title is present" if title_present else "Product title is missing"},
        {"code": "CATEGORY_RULES", "passed": category_present, "message": "Category is present" if category_present else "Category is missing"},
        {"code": "SKU_RULES", "passed": sku_present, "message": "At least one SKU is present" if sku_present else "Product has no SKU"},
        {"code": "SKU_PRICE_RULES", "passed": sku_prices_valid, "message": "SKU prices and currencies are valid" if sku_prices_valid else "A SKU has no valid price or currency"},
        {"code": "MEDIA_RULES", "passed": media_refs_valid, "message": "Media references are present and valid" if media_refs_valid else "Product or SKU media references are missing or invalid"},
    ]


@router.get("/admin/v1/dashboard", response_model=DashboardMetricsResponse)
async def dashboard(
    _: SimpleNamespace = Depends(require_permission("dashboard.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    pending_query = select(func.count()).select_from(ModerationCard).where(
        ModerationCard.status.in_([ModerationStatus.CREATED, ModerationStatus.PENDING])
    )
    pending = int(await db.scalar(pending_query) or 0)
    in_review = int(await db.scalar(
        select(func.count()).select_from(ModerationCard).where(ModerationCard.status == ModerationStatus.IN_REVIEW)
    ) or 0)
    overdue = int(await db.scalar(
        select(func.count()).select_from(ModerationCard).where(
            ModerationCard.status.in_([ModerationStatus.CREATED, ModerationStatus.PENDING]),
            ModerationCard.created_at <= now - timedelta(seconds=settings.moderation_ticket_sla_seconds),
        )
    ) or 0)
    oldest_created_at = await db.scalar(
        select(func.min(ModerationCard.created_at)).where(
            ModerationCard.status.in_([ModerationStatus.CREATED, ModerationStatus.PENDING])
        )
    )
    complaint_pending_statuses = ("NEW", "TRIAGED")
    complaint_active_statuses = ("NEW", "TRIAGED", "IN_REVIEW", "ESCALATED")
    complaints_pending = int(await db.scalar(
        select(func.count()).select_from(Complaint).where(Complaint.status.in_(complaint_pending_statuses))
    ) or 0)
    complaints_in_review = int(await db.scalar(
        select(func.count()).select_from(Complaint).where(Complaint.status.in_(("IN_REVIEW", "ESCALATED")))
    ) or 0)
    complaints_overdue = int(await db.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.status.in_(complaint_active_statuses),
            Complaint.deadline_at.is_not(None),
            Complaint.deadline_at <= now,
        )
    ) or 0)
    oldest_complaint_created_at = await db.scalar(
        select(func.min(Complaint.created_at)).where(Complaint.status.in_(complaint_pending_statuses))
    )
    moderator_workload = (await db.execute(
        select(ModerationCard.moderator_id, func.count())
        .where(
            ModerationCard.status == ModerationStatus.IN_REVIEW,
            ModerationCard.moderator_id.is_not(None),
        )
        .group_by(ModerationCard.moderator_id)
        .order_by(ModerationCard.moderator_id)
    )).all()
    resolved_decisions = (await db.execute(
        select(
            func.count(),
            func.avg(extract("epoch", AdminOperation.updated_at - AdminOperation.created_at)),
        )
        .select_from(AdminOperation)
        .join(ModerationDecisionReceipt, ModerationDecisionReceipt.id == AdminOperation.id)
        .where(
            AdminOperation.action == "MODERATION_DECISION",
            AdminOperation.status.in_(("APPLIED", "FAILED")),
            ModerationDecisionReceipt.action.in_(("APPROVE", "CHANGES_REQUESTED", "REJECT", "HARD_BLOCK")),
        )
    )).one()
    outbox_pending = int(await db.scalar(
        select(func.count()).select_from(ModerationOutboxEvent).where(
            ModerationOutboxEvent.status.in_(["PENDING", "RETRY", "LEASED", "WAITING_ACK"])
        )
    ) or 0)
    outbox_dead = int(await db.scalar(
        select(func.count()).select_from(ModerationOutboxEvent).where(ModerationOutboxEvent.status == "DEAD")
    ) or 0)
    return {
        "as_of": now,
        "provenance": {
            "moderation": "moderation_cards.status,created_at; MODERATION_TICKET_SLA_SECONDS",
            "workload_by_moderator": "moderation_cards.moderator_id,status",
            "resolution_time": "admin_operations.created_at,updated_at,status joined moderation_decision_receipts.action",
            "complaints": "admin_complaints.status,created_at,deadline_at",
            "outbox": "moderation_outbox_events.status,created_at",
        },
        "workload_by_moderator": [
            {"staff_id": staff_id, "in_review": int(count)}
            for staff_id, count in moderator_workload
        ],
        "pending": pending,
        "in_review": in_review,
        "overdue": overdue,
        "complaints_pending": complaints_pending,
        "complaints_in_review": complaints_in_review,
        "complaints_overdue": complaints_overdue,
        "average_resolution_seconds": (
            float(resolved_decisions[1]) if resolved_decisions[1] is not None else None
        ),
        "resolved_decision_count": int(resolved_decisions[0]),
        "oldest_pending_seconds": max(0, int((now - oldest_created_at).total_seconds())) if oldest_created_at else 0,
        "oldest_complaint_pending_seconds": (
            max(0, int((now - oldest_complaint_created_at).total_seconds())) if oldest_complaint_created_at else 0
        ),
        "outbox_pending": outbox_pending,
        "outbox_dead": outbox_dead,
    }


@router.get("/admin/v1/audit-events", response_model=AuditPage, response_model_exclude_none=True)
async def list_audit_events(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    actor: SimpleNamespace = Depends(require_permission("audit.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cursor_value = _decode_audit_cursor(cursor)
    query = select(AuditLog)
    if cursor_value is not None:
        created_at, event_id = cursor_value
        query = query.where(
            (AuditLog.created_at < created_at)
            | ((AuditLog.created_at == created_at) & (AuditLog.id < event_id))
        )
    result = await db.execute(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1))
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    db.add(AuditLog(
        actor_id=actor.id,
        action="AUDIT_EVENTS_READ",
        entity_type="audit_log_collection",
        entity_id=actor.id,
        details={"returned_count": len(rows), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return {
        "items": [
        {
            "id": str(item.id),
            "actor_id": str(item.actor_id) if item.actor_id else None,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": str(item.entity_id),
            "created_at": item.created_at,
            "request_id": item.request_id,
        }
            for item in rows
        ],
        "page": {
            "has_more": has_more,
            "next_cursor": _audit_cursor(rows[-1]) if has_more and rows else None,
        },
    }


def _decode_audit_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
        created_at = datetime.fromisoformat(value["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor timestamp must include timezone")
        return created_at.astimezone(timezone.utc), UUID(value["id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid audit cursor"}) from exc


def _audit_cursor(event: AuditLog) -> str:
    raw = json.dumps({"t": event.created_at.isoformat(), "id": str(event.id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _redacted_ticket_history_details(event: AuditLog) -> dict[str, object]:
    details = event.details if isinstance(event.details, dict) else {}
    passed_rules = details.get("passed_rules")
    if event.action != "TICKET_DECISION_APPROVE" or not isinstance(passed_rules, list):
        return {}
    return {
        "passed_rules": [
            code for code in passed_rules
            if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code)
        ]
    }


def _decode_ticket_cursor(cursor: str | None):
    if not isinstance(cursor, str) or not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
        created_at = datetime.fromisoformat(value["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor timestamp must include a timezone")
        return int(value["p"]), created_at.astimezone(timezone.utc), UUID(value["id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid ticket cursor"}) from exc


def _ticket_cursor(card: ModerationCard) -> str:
    raw = json.dumps({"p": card.queue_priority, "t": card.created_at.isoformat(), "id": str(card.id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


@router.get("/admin/v1/moderation/tickets", response_model=TicketPageResponse, response_model_exclude_none=True)
@router.get("/api/v1/tickets", include_in_schema=False)
async def list_tickets(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    status_filter: ModerationStatus | None = Query(None, alias="status"),
    priority: int | None = Query(None, ge=0),
    seller_id: UUID | None = Query(None),
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.ticket.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    permission_scopes = getattr(current_moderator, "permission_scopes", {}).get("moderation.ticket.read", set())
    seller_scopes: set[UUID] | None = None
    if "*" not in current_moderator.permissions and "*" not in permission_scopes:
        seller_scopes = {
            UUID(scope.removeprefix("seller:"))
            for scope in permission_scopes
            if scope.startswith("seller:")
        }
    items, has_more = await ModerationService(db).list_tickets_keyset(
        limit=limit,
        status_filter=status_filter,
        priority=priority,
        seller_id=seller_id,
        seller_ids=seller_scopes if seller_id is None else None,
        cursor=_decode_ticket_cursor(cursor),
    )
    response = {
        "items": [_ticket_response(item) for item in items],
        "page": {
            "has_more": has_more,
            "next_cursor": _ticket_cursor(items[-1]) if has_more and items else None,
        },
    }
    db.add(AuditLog(
        actor_id=current_moderator.id,
        action="MODERATION_QUEUE_READ",
        entity_type="moderation_queue",
        entity_id=current_moderator.id,
        details={"returned_count": len(items), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return response


@router.get("/admin/v1/moderation/tickets/{ticket_id}", response_model=TicketDetailResponse, response_model_exclude_none=True)
async def get_ticket(
    ticket_id: UUID,
    actor: SimpleNamespace = Depends(require_permission("moderation.ticket.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    card = await ModerationService(db).repo.get_with_skus(ticket_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Moderation card not found")
    snapshot = await db.scalar(
        select(ModerationSnapshot).where(
            ModerationSnapshot.ticket_id == ticket_id,
            ModerationSnapshot.revision == card.submitted_revision,
        )
    ) if card.submitted_revision is not None else None
    if snapshot is None:
        raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Immutable product snapshot is unavailable for this historical ticket"})
    try:
        ticket_source_hash = normalize_source_digest(card.snapshot_hash)
        stored_source_hash = normalize_source_digest(snapshot.snapshot_hash)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Pinned source snapshot hash is invalid"}) from exc
    if not hmac.compare_digest(ticket_source_hash, stored_source_hash):
        raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Ticket and stored snapshot hashes do not match"})
    verified_hash = hashlib.sha256(
        json.dumps(snapshot.content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(verified_hash, snapshot.content_hash):
        raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Stored product snapshot failed its integrity check"})
    attributes = snapshot.content.get("attributes", snapshot.content.get("characteristics"))
    if not isinstance(attributes, dict):
        raise HTTPException(status_code=503, detail={"code": "SNAPSHOT_INCOMPLETE", "message": "The pinned product snapshot has no structured attributes"})
    policy_version = snapshot.content.get("policy_version")
    if type(policy_version) is not int or policy_version < 1:
        raise HTTPException(status_code=503, detail={"code": "SNAPSHOT_INCOMPLETE", "message": "The pinned product snapshot has no valid policy version"})
    if snapshot.policy_version is not None and snapshot.policy_version != policy_version:
        raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Pinned snapshot policy version does not match its immutable content"})
    snapshot_data = {
        key: snapshot.content[key]
        for key in ("title", "description", "category_id", "images", "skus")
        if key in snapshot.content
    }
    snapshot_data.update({
        "product_id": card.product_id,
        "seller_id": card.seller_id,
        "revision": snapshot.revision,
        "snapshot_hash": snapshot.snapshot_hash,
        "attributes": attributes,
        "policy_version": policy_version,
    })
    snapshot_data.setdefault("skus", [])
    try:
        snapshot_view = ProductSnapshotResponse.model_validate(snapshot_data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SNAPSHOT_CONTRACT_UNAVAILABLE", "message": "The pinned product snapshot does not satisfy the Admin review contract"},
        ) from exc
    # B2B is queried after releasing the Admin read transaction. Copy fields
    # needed below first because AsyncSession expires ORM instances on commit.
    ticket_view = _ticket_response(card)
    ticket_product_id = card.product_id
    ticket_seller_id = card.seller_id
    ticket_submitted_revision = card.submitted_revision
    snapshot_revision = snapshot.revision
    snapshot_hash = snapshot.snapshot_hash
    snapshot_content = snapshot.content
    await db.commit()
    b2b = B2BClient()
    publication_data = await b2b.get_internal_json(f"/internal/v1/products/{ticket_product_id}/publication")
    try:
        publication = ProductPublication.model_validate(publication_data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PUBLICATION", "message": "B2B returned an invalid publication status"}) from exc
    if (
        publication.product_id != ticket_product_id
        or publication.current_revision < snapshot_revision
        or (publication.published_revision is not None and publication.published_revision > publication.current_revision)
    ):
        raise HTTPException(status_code=502, detail={"code": "B2B_PUBLICATION_MISMATCH", "message": "B2B publication state does not match the pinned product revision"})
    field_diff = None
    if publication.published_revision is not None:
        if publication.published_revision == snapshot_revision:
            published_content = snapshot_content
        else:
            published_data = await b2b.get_internal_json(
                f"/internal/v1/products/{ticket_product_id}/revisions/{publication.published_revision}"
            )
            try:
                published_revision = ProductRevisionSnapshot.model_validate(published_data)
                normalize_source_digest(published_revision.snapshot_hash)
            except (ValidationError, ValueError) as exc:
                raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PUBLISHED_REVISION", "message": "B2B returned an invalid published product revision"}) from exc
            if (
                published_revision.product_id != ticket_product_id
                or published_revision.revision != publication.published_revision
                or (ticket_seller_id is not None and published_revision.seller_id != ticket_seller_id)
            ):
                raise HTTPException(status_code=502, detail={"code": "B2B_PUBLISHED_REVISION_MISMATCH", "message": "B2B returned a different published product revision"})
            published_content = published_revision.content
        published_attributes = published_content.get("attributes")
        if published_attributes is None:
            published_attributes = published_content.get("characteristics")
        published_policy_version = published_content.get("policy_version")
        if not isinstance(published_attributes, dict) or type(published_policy_version) is not int or published_policy_version < 1:
            raise HTTPException(status_code=502, detail={"code": "B2B_PUBLISHED_SNAPSHOT_INCOMPLETE", "message": "Published product revision is missing structured attributes or policy version"})
        published_snapshot_data = {
            key: published_content[key]
            for key in ("title", "description", "category_id", "images", "skus")
            if key in published_content
        }
        published_snapshot_data.update({
            "product_id": ticket_product_id,
            "seller_id": ticket_seller_id,
            "revision": publication.published_revision,
            "snapshot_hash": snapshot_hash if publication.published_revision == snapshot_revision else published_revision.snapshot_hash,
            "attributes": published_attributes,
            "policy_version": published_policy_version,
        })
        published_snapshot_data.setdefault("skus", [])
        try:
            published_snapshot = ProductSnapshotResponse.model_validate(published_snapshot_data)
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_PUBLISHED_SNAPSHOT_INVALID", "message": "Published product revision does not satisfy the Admin review contract"}) from exc
        field_diff = _snapshot_field_diff(
            _reviewable_snapshot_fields(published_snapshot),
            _reviewable_snapshot_fields(snapshot_view),
        )
    response = {
        "ticket": ticket_view,
        "snapshot": snapshot_view,
        "published_revision": publication.published_revision,
        "field_diff": field_diff,
        "checklist": _review_checklist(
            snapshot_view,
            revision_pinned=ticket_submitted_revision == snapshot_revision,
            published_loaded=publication.published_revision is not None,
        ),
    }
    db.add(AuditLog(
        actor_id=actor.id,
        action="MODERATION_TICKET_READ",
        entity_type="moderation_ticket",
        entity_id=ticket_id,
        details={"product_revision": snapshot_revision},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return response


@router.get("/admin/v1/moderation/tickets/{ticket_id}/history", response_model=AuditPage)
async def get_ticket_history(
    ticket_id: UUID,
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    actor: SimpleNamespace = Depends(require_permission("moderation.ticket.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    exists = await db.scalar(
        select(ModerationCard.id).where(ModerationCard.id == ticket_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Moderation card not found")
    cursor_value = _decode_audit_cursor(cursor)
    query = select(AuditLog).where(AuditLog.entity_id == ticket_id)
    if cursor_value is not None:
        created_at, event_id = cursor_value
        query = query.where(
            (AuditLog.created_at < created_at)
            | ((AuditLog.created_at == created_at) & (AuditLog.id < event_id))
        )
    result = await db.execute(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1))
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    response = {
        "items": [
            {
                "id": item.id,
                "action": item.action,
                "actor_id": item.actor_id,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "created_at": item.created_at,
                "request_id": item.request_id,
                "redacted_details": _redacted_ticket_history_details(item),
            }
            for item in rows
        ],
        "page": {"has_more": has_more, "next_cursor": _audit_cursor(rows[-1]) if has_more and rows else None},
    }
    db.add(AuditLog(
        actor_id=actor.id,
        action="MODERATION_TICKET_HISTORY_READ",
        entity_type="moderation_ticket",
        entity_id=ticket_id,
        details={"returned_count": len(rows), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return response


@router.post("/admin/v1/moderation/tickets/{ticket_id}/claim", response_model=ClaimResult, response_model_exclude_none=True)
@router.post("/api/v1/tickets/{ticket_id}/claim", response_model=ModerationCardResponse, include_in_schema=False)
async def claim_ticket(
    ticket_id: UUID,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.ticket.claim")),
    db: AsyncSession = Depends(get_db),
) -> ClaimResult:
    card = await ModerationService(db).claim_ticket(
        ticket_id,
        current_moderator.id,
        expected_version=_parse_if_match(if_match),
        idempotency_key=idempotency_key,
    )
    result = ClaimResult(
        ticket=_ticket_response(card),
        claim_token=card.claim_token,
        lease_expires_at=card.lease_expires_at,
        fencing_version=card.fencing_version,
    )
    await db.commit()
    return result


@router.post("/admin/v1/moderation/tickets/{ticket_id}/release", response_model=ModerationCardResponse, response_model_exclude_none=True)
@router.post("/api/v1/tickets/{ticket_id}/release", response_model=ModerationCardResponse, include_in_schema=False)
async def release_ticket(
    ticket_id: UUID,
    lease: LeaseInput,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.ticket.claim")),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).release_ticket(
        ticket_id,
        current_moderator.id,
        lease.claim_token,
        fencing_version=lease.fencing_version,
        expected_version=_parse_if_match(if_match),
        idempotency_key=idempotency_key,
    )
    result = _ticket_response(card)
    await db.commit()
    return result


@router.post("/admin/v1/moderation/tickets/{ticket_id}/heartbeat", response_model=ClaimResult, response_model_exclude_none=True)
@router.post("/api/v1/tickets/{ticket_id}/heartbeat", response_model=ModerationCardResponse, include_in_schema=False)
async def heartbeat_ticket(
    ticket_id: UUID,
    lease: LeaseInput,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.ticket.claim")),
    db: AsyncSession = Depends(get_db),
) -> ClaimResult:
    card = await ModerationService(db).heartbeat_ticket(
        ticket_id,
        current_moderator.id,
        lease.claim_token,
        fencing_version=lease.fencing_version,
        expected_version=_parse_if_match(if_match),
        idempotency_key=idempotency_key,
    )
    result = ClaimResult(
        ticket=_ticket_response(card),
        claim_token=lease.claim_token,
        lease_expires_at=card.lease_expires_at,
        fencing_version=card.fencing_version,
    )
    await db.commit()
    return result


@router.post("/admin/v1/moderation/tickets/{ticket_id}/decisions", response_model=DecisionResult, status_code=202)
async def decide_ticket(
    ticket_id: UUID,
    data: DecisionInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.decision.write")),
    db: AsyncSession = Depends(get_db),
) -> DecisionResult:
    expected_version = _parse_if_match(if_match)
    if data.action == "HARD_BLOCK" and "*" not in current_moderator.permissions and "moderation.hard_block" not in current_moderator.permissions:
        await _record_access_denial(db, request, "moderation.hard_block")
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Hard block permission is required"})
    if data.action == "HARD_BLOCK":
        try:
            await authorize_permission_scope("moderation.hard_block", request, current_moderator, db)
            require_recent_step_up(current_moderator)
        except HTTPException as exc:
            if exc.status_code == 403:
                await _record_access_denial(db, request, "moderation.hard_block")
            raise
    receipt = await ModerationService(db).decide_ticket(
        ticket_id,
        current_moderator.id,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        action=data.action,
        claim_token=data.claim_token,
        product_revision=data.product_revision,
        snapshot_hash=data.snapshot_hash,
        reason_codes=data.reason_codes,
        passed_rules=data.passed_rules,
        field_reports=[report.model_dump(mode="json") for report in data.field_reports],
        comment=data.comment,
        policy_version=data.policy_version,
    )
    await db.commit()
    return DecisionResult(
        decision_id=receipt.id,
        operation_id=receipt.id,
        status=receipt.result_status,
        ticket_id=receipt.ticket_id,
    )


def _parse_if_match(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        version = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain the ticket version"}) from exc
    if version < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match version must be positive"})
    return version


@router.post("/api/v1/tickets/{ticket_id}/approve", response_model=ModerationCardResponse, include_in_schema=False)
async def approve_ticket(
    ticket_id: UUID,
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.decision.write")),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    raise HTTPException(status_code=410, detail={"code": "LEGACY_DECISION_DISABLED", "message": "Use the revision-bound decisions endpoint"})


@router.post(
    "/api/v1/moderation/{card_id}/approve",
    response_model=ModerationCardResponse,
    include_in_schema=False,
)
@router.post(
    "/api/v1/products/{card_id}/approve",
    response_model=ModerationCardResponse,
    include_in_schema=False,
)
async def approve_product(
    card_id: UUID,
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.decision.write")),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    raise HTTPException(status_code=410, detail={"code": "LEGACY_DECISION_DISABLED", "message": "Use the revision-bound decisions endpoint"})


@router.post("/api/v1/tickets/{ticket_id}/block", response_model=ModerationCardResponse, include_in_schema=False)
async def block_ticket(
    ticket_id: UUID,
    data: BlockDecisionRequest,
    current_moderator: SimpleNamespace = Depends(require_permission("moderation.decision.write")),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    raise HTTPException(status_code=410, detail={"code": "LEGACY_DECISION_DISABLED", "message": "Use the revision-bound decisions endpoint"})


@router.get("/api/v1/blocking-reasons", response_model=list[BlockingReasonResponse], include_in_schema=False)
async def list_blocking_reasons(
    hard_block: bool | None = None,
    _: SimpleNamespace = Depends(require_permission("moderation.ticket.read")),
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonResponse]:
    return await ModerationService(db).list_blocking_reasons(hard_block=hard_block)


@router.post(
    "/internal/v1/events/products",
    status_code=202,
    responses={200: {"description": "Already applied"}},
)
async def apply_product_event_envelope(
    event: ProductEventEnvelope,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if event.event_type in {
        "product.publication.applied.v1",
        "product.publication.rejected.v1",
    }:
        decision_event = PublicationDecisionEnvelope.model_validate(
            event.model_dump(mode="json")
        )
        result = await ModerationService(db).apply_publication_decision_event(
            decision_event
        )
        await db.commit()
        return result

    event_type = {
        "product.deleted": "PRODUCT_DELETED",
        "product.updated": "PRODUCT_EDITED",
        "product.created": "PRODUCT_CREATED",
    }[event.event_type]
    result = await ModerationService(db).apply_product_event(
        {
            "event_type": event_type,
            "product_id": str(event.aggregate_id),
            "aggregate_version": event.aggregate_version,
            "seller_id": str(event.payload["seller_id"]) if event.payload.get("seller_id") else None,
            "idempotency_key": str(event.event_id),
            "occurred_at": event.occurred_at,
            "payload": event.payload,
        }
    )
    await db.commit()
    return result


@router.post("/api/v1/b2b/events", include_in_schema=False)
@router.post("/api/v1/events/products", include_in_schema=False)
async def apply_product_event(
    event: ProductEventRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await ModerationService(db).apply_product_event(event.model_dump(mode="json"))
    await db.commit()
    return result
