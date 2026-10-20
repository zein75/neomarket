from datetime import datetime, timedelta, timezone
import math
import hashlib
import hmac
import json
from uuid import NAMESPACE_URL, UUID, uuid5
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, update

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.models.processed_product_event import ProcessedProductEvent
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_claim_receipt import ModerationClaimReceipt
from src.models.moderation import BlockingReason, ModerationCard, ModerationSKU, ModerationStatus
from src.models.moderation_snapshot import ModerationSnapshot
from src.repositories.moderation_repo import ModerationRepository
from src.schemas.moderation import FieldReport, PublicationDecisionEnvelope
from src.services.product_snapshots import content_digest, normalize_source_digest
from src.services.runtime_settings import effective_values


class ModerationService:
    MAX_OUTBOX_ATTEMPTS = 12
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ModerationRepository(session)

    async def list_blocking_reasons(self, *, hard_block: bool | None = None):
        return await self.repo.list_all_blocking_reasons(hard_block=hard_block)

    async def list_tickets_keyset(
        self,
        *,
        limit: int,
        status_filter: ModerationStatus | None = None,
        priority: int | None = None,
        seller_id: UUID | None = None,
        seller_ids: set[UUID] | None = None,
        cursor=None,
    ):
        return await self.repo.list_tickets_keyset(
            limit=limit,
            status=status_filter,
            priority=priority,
            seller_id=seller_id,
            seller_ids=seller_ids,
            cursor=cursor,
        )

    async def _ensure_decision_operation(
        self,
        receipt: ModerationDecisionReceipt,
        *,
        status_value: str | None = None,
    ) -> AdminOperation:
        operation = await self.repo.session.get(AdminOperation, receipt.id)
        if operation is not None:
            if operation.action != "MODERATION_DECISION":
                raise HTTPException(
                    status_code=409,
                    detail={"code": "OPERATION_ID_CONFLICT", "message": "Decision operation ID is already in use"},
                )
            return operation
        card = await self.repo.session.get(ModerationCard, receipt.ticket_id)
        if card is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "DECISION_TICKET_MISSING", "message": "Decision ticket is unavailable"},
            )
        resolved_status = status_value
        if resolved_status is None:
            if receipt.action == "ESCALATE" or card.status in {
                ModerationStatus.MODERATED,
                ModerationStatus.WAITING_SELLER,
                ModerationStatus.BLOCKED,
                ModerationStatus.HARD_BLOCKED,
            }:
                resolved_status = "APPLIED"
            elif card.status == ModerationStatus.STALE:
                resolved_status = "FAILED"
            else:
                resolved_status = "RUNNING"
        operation = AdminOperation(
            id=receipt.id,
            action="MODERATION_DECISION",
            entity_type="moderation_ticket",
            entity_id=receipt.ticket_id,
            payload={
                "decision_id": str(receipt.id),
                "product_id": str(card.product_id),
                "submitted_revision": receipt.product_revision,
                "action": receipt.action,
                "policy_version": receipt.policy_version,
            },
            status=resolved_status,
            version=1,
            idempotency_key=f"moderation:{receipt.idempotency_key}",
            request_hash=receipt.request_hash,
            requested_by=receipt.actor_id,
            reason_code=(receipt.reason_codes or ["MODERATION_DECISION"])[0],
            updated_at=datetime.now(timezone.utc),
        )
        self.repo.session.add(operation)
        await self.repo.session.flush()
        return operation

    async def claim_ticket(
        self,
        card_id: UUID,
        moderator_id: UUID,
        *,
        expected_version: int | None = None,
        idempotency_key: UUID | None = None,
    ):
        idempotency_key = idempotency_key or uuid4()
        request_hash = hashlib.sha256(
            f"{card_id}:{moderator_id}:{expected_version}".encode("ascii")
        ).hexdigest()
        scalar = getattr(self.repo.session, "scalar", None)
        previous = await scalar(
            select(ModerationClaimReceipt).where(
                ModerationClaimReceipt.actor_id == moderator_id,
                ModerationClaimReceipt.idempotency_key == str(idempotency_key),
            )
        ) if callable(scalar) else None
        if previous is not None:
            if previous.operation != "CLAIM" or previous.ticket_id != card_id or not hmac.compare_digest(previous.request_hash, request_hash):
                raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Claim key was used for a different request"})
            card = await self.repo.get_with_skus_for_update(card_id)
            if card is None or card.fencing_version != previous.fencing_version or previous.lease_expires_at <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail={"code": "CLAIM_REPLAY_EXPIRED", "message": "The original claim lease is no longer active"})
            await self._require_pinned_snapshot(card_id, card)
            card.claim_token = self._claim_token(card_id, moderator_id, idempotency_key, previous.fencing_version)
            return card
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        # The initial receipt lookup is only a fast replay path. Two requests
        # carrying the same actor/key can both miss it before either obtains
        # the ticket lock, so check again after serialization. This keeps a
        # concurrent retry from creating a second lease or hitting the unique
        # receipt constraint as an internal error.
        previous = await scalar(
            select(ModerationClaimReceipt).where(
                ModerationClaimReceipt.actor_id == moderator_id,
                ModerationClaimReceipt.idempotency_key == str(idempotency_key),
            )
        ) if callable(scalar) else None
        if previous is not None:
            if previous.operation != "CLAIM" or previous.ticket_id != card_id or not hmac.compare_digest(previous.request_hash, request_hash):
                raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Claim key was used for a different request"})
            if card.fencing_version != previous.fencing_version or previous.lease_expires_at <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail={"code": "CLAIM_REPLAY_EXPIRED", "message": "The original claim lease is no longer active"})
            await self._require_pinned_snapshot(card_id, card)
            card.claim_token = self._claim_token(card_id, moderator_id, idempotency_key, previous.fencing_version)
            return card
        await self._require_pinned_snapshot(card_id, card)
        if expected_version is not None and int(getattr(card, "version", 1)) != expected_version:
            raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Ticket has changed; reload before claiming"})
        queue_settings, _ = await effective_values(self.repo.session, "queue_policy")
        claim_ttl_seconds = int(queue_settings["moderation_claim_ttl_seconds"])
        now = datetime.now(timezone.utc)
        lease_expires_at = getattr(card, "lease_expires_at", None)
        legacy_claim_is_stale = (
            getattr(card, "lease_token_hash", None) is None
            and getattr(card, "updated_at", None) is not None
            and card.updated_at < now - timedelta(seconds=claim_ttl_seconds)
        )
        stale = bool((lease_expires_at and lease_expires_at <= now) or legacy_claim_is_stale)
        if card.moderator_id not in (None, moderator_id) and not stale:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_ALREADY_ASSIGNED", "message": "Ticket is assigned to another moderator"},
            )
        if card.status not in {ModerationStatus.CREATED, ModerationStatus.PENDING} and not stale:
            raise HTTPException(
                status_code=409,
                detail={"code": "CLAIM_NOT_ALLOWED", "message": "Ticket cannot be claimed in current status"},
            )
        card.moderator_id = moderator_id
        card.status = ModerationStatus.IN_REVIEW
        claim_token = self._claim_token(card_id, moderator_id, idempotency_key, int(getattr(card, "fencing_version", 0)) + 1)
        card.lease_token_hash = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
        card.lease_expires_at = now + timedelta(seconds=claim_ttl_seconds)
        card.fencing_version = int(getattr(card, "fencing_version", 0)) + 1
        card.version = int(getattr(card, "version", 1)) + 1
        card.updated_at = now
        add = getattr(self.repo.session, "add", None)
        if callable(add):
            add(ModerationClaimReceipt(
                ticket_id=card_id,
                actor_id=moderator_id,
                idempotency_key=str(idempotency_key),
                request_hash=request_hash,
                fencing_version=card.fencing_version,
                lease_expires_at=card.lease_expires_at,
            ))
        # Only returned in this response; never mapped or persisted.
        card.claim_token = claim_token
        self._audit(moderator_id, "TICKET_CLAIM", card.id)
        await self.repo.session.flush()
        return card

    async def _require_pinned_snapshot(self, ticket_id: UUID, card: object) -> None:
        revision = getattr(card, "submitted_revision", None)
        source_hash = getattr(card, "snapshot_hash", None)
        if revision is None or not source_hash:
            raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Ticket has no verified immutable product snapshot"})
        snapshot = await self.repo.session.scalar(
            select(ModerationSnapshot).where(
                ModerationSnapshot.ticket_id == ticket_id,
                ModerationSnapshot.revision == revision,
            )
        )
        if snapshot is None or not hmac.compare_digest(snapshot.snapshot_hash, source_hash):
            raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Pinned product snapshot is missing or inconsistent"})
        if not hmac.compare_digest(content_digest(snapshot.content), snapshot.content_hash):
            raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Pinned product snapshot failed its integrity check"})

    def _claim_token(self, ticket_id: UUID, actor_id: UUID, key: UUID, fencing_version: int) -> str:
        message = f"{ticket_id}:{actor_id}:{key}:{fencing_version}".encode("ascii")
        return hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()

    async def release_ticket(
        self,
        card_id: UUID,
        moderator_id: UUID,
        claim_token: str | None = None,
        *,
        fencing_version: int | None = None,
        expected_version: int | None = None,
        idempotency_key: UUID | None = None,
    ):
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        request_hash = self._lease_request_hash(card_id, moderator_id, "RELEASE", claim_token or "", fencing_version or 0, expected_version or 0)
        replay = await self._replay_lease_operation(card, moderator_id, idempotency_key, "RELEASE", request_hash) if idempotency_key else None
        if replay:
            return replay
        if card.moderator_id != moderator_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_NOT_ASSIGNED", "message": "Ticket is assigned to another moderator"},
            )
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=409,
                detail={"code": "RELEASE_NOT_ALLOWED", "message": "Ticket is not in review"},
            )
        if claim_token is not None and fencing_version is not None and expected_version is not None:
            self._validate_lease(card, moderator_id, claim_token, fencing_version, expected_version)
        card.moderator_id = None
        card.status = ModerationStatus.PENDING
        card.lease_token_hash = None
        card.lease_expires_at = None
        card.version = int(getattr(card, "version", 1)) + 1
        if idempotency_key is not None and fencing_version is not None:
            self._record_lease_operation(card_id, moderator_id, idempotency_key, "RELEASE", request_hash, fencing_version, datetime.now(timezone.utc))
        self._audit(moderator_id, "TICKET_RELEASE", card.id)
        await self.repo.session.flush()
        return card

    async def heartbeat_ticket(
        self,
        card_id: UUID,
        moderator_id: UUID,
        claim_token: str | None = None,
        *,
        fencing_version: int | None = None,
        expected_version: int | None = None,
        idempotency_key: UUID | None = None,
    ):
        card = await self.repo.get_with_skus_for_update(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Moderation card not found")
        request_hash = self._lease_request_hash(card_id, moderator_id, "HEARTBEAT", claim_token or "", fencing_version or 0, expected_version or 0)
        replay = await self._replay_lease_operation(card, moderator_id, idempotency_key, "HEARTBEAT", request_hash, claim_token) if idempotency_key else None
        if replay:
            return replay
        if card.moderator_id != moderator_id or card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_NOT_ASSIGNED", "message": "Ticket is not assigned to this moderator"},
            )
        if claim_token is not None and fencing_version is not None and expected_version is not None:
            self._validate_lease(card, moderator_id, claim_token, fencing_version, expected_version)
        queue_settings, _ = await effective_values(self.repo.session, "queue_policy")
        card.updated_at = datetime.now(timezone.utc)
        card.lease_expires_at = card.updated_at + timedelta(seconds=int(queue_settings["moderation_claim_ttl_seconds"]))
        card.version = int(getattr(card, "version", 1)) + 1
        if idempotency_key is not None and fencing_version is not None:
            self._record_lease_operation(card_id, moderator_id, idempotency_key, "HEARTBEAT", request_hash, fencing_version, card.lease_expires_at)
        self._audit(moderator_id, "TICKET_HEARTBEAT", card.id)
        await self.repo.session.flush()
        return card

    def _lease_request_hash(self, ticket_id: UUID, actor_id: UUID, operation: str, token: str, fence: int, version: int) -> str:
        payload = f"{ticket_id}:{actor_id}:{operation}:{hashlib.sha256(token.encode()).hexdigest()}:{fence}:{version}"
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    async def _replay_lease_operation(
        self,
        card: object,
        actor_id: UUID,
        key: UUID,
        operation: str,
        request_hash: str,
        claim_token: str | None = None,
    ):
        scalar = getattr(self.repo.session, "scalar", None)
        if not callable(scalar):
            return None
        receipt = await scalar(
            select(ModerationClaimReceipt).where(
                ModerationClaimReceipt.actor_id == actor_id,
                ModerationClaimReceipt.idempotency_key == str(key),
            )
        )
        if receipt is None:
            return None
        if receipt.operation != operation or receipt.ticket_id != card.id or not hmac.compare_digest(receipt.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Lease key was used for a different request"})
        if claim_token is not None:
            card.claim_token = claim_token
        return card

    def _record_lease_operation(
        self, ticket_id: UUID, actor_id: UUID, key: UUID, operation: str,
        request_hash: str, fencing_version: int, lease_expires_at: datetime,
    ) -> None:
        add = getattr(self.repo.session, "add", None)
        if not callable(add):
            return
        add(
            ModerationClaimReceipt(
                ticket_id=ticket_id,
                actor_id=actor_id,
                idempotency_key=str(key),
                operation=operation,
                request_hash=request_hash,
                fencing_version=fencing_version,
                lease_expires_at=lease_expires_at,
            )
        )

    def _validate_lease(
        self,
        card: object,
        moderator_id: UUID,
        claim_token: str,
        fencing_version: int,
        expected_version: int,
    ) -> None:
        if int(getattr(card, "version", 0)) != expected_version:
            raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Ticket has changed; reload before continuing"})
        if int(getattr(card, "fencing_version", 0)) != fencing_version:
            raise HTTPException(status_code=409, detail={"code": "LEASE_FENCED", "message": "Claim lease was replaced"})
        self._validate_claim_token(card, claim_token)
        expires_at = getattr(card, "lease_expires_at", None)
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail={"code": "LEASE_EXPIRED", "message": "Claim lease expired; claim the ticket again"})

    async def decide_ticket(
        self,
        ticket_id: UUID,
        moderator_id: UUID,
        *,
        idempotency_key: UUID,
        expected_version: int,
        action: str,
        claim_token: str,
        product_revision: int,
        snapshot_hash: str,
        reason_codes: list[str] | None = None,
        passed_rules: list[str] | None = None,
        field_reports: list[dict[str, object]] | None = None,
        comment: str | None = None,
        policy_version: int,
    ) -> ModerationDecisionReceipt:
        """Apply a revision-pinned decision with CAS, fencing and replay safety."""
        request_data = {
            "ticket_id": str(ticket_id),
            "action": action,
            "claim_token_hash": hashlib.sha256(claim_token.encode("utf-8")).hexdigest(),
            "product_revision": product_revision,
            "snapshot_hash": snapshot_hash,
            "reason_codes": sorted(reason_codes or []),
            "passed_rules": sorted(passed_rules or []),
            "field_reports": field_reports or [],
            "comment": comment,
            "policy_version": policy_version,
            "expected_version": expected_version,
        }
        request_hash = hashlib.sha256(
            json.dumps(request_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        existing = await self.repo.session.scalar(
            select(ModerationDecisionReceipt).where(
                ModerationDecisionReceipt.actor_id == moderator_id,
                ModerationDecisionReceipt.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            if existing.ticket_id != ticket_id or not hmac.compare_digest(existing.request_hash, request_hash):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different decision"},
                )
            await self._ensure_decision_operation(existing)
            return existing

        card = await self.repo.get_with_skus_for_update(ticket_id)
        if card is None:
            raise HTTPException(status_code=404, detail={"code": "TICKET_NOT_FOUND", "message": "Moderation ticket not found"})
        # A concurrent request with the same key may have committed while this
        # transaction waited on the ticket row lock. Recheck before CAS checks.
        existing = await self.repo.session.scalar(
            select(ModerationDecisionReceipt).where(
                ModerationDecisionReceipt.actor_id == moderator_id,
                ModerationDecisionReceipt.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            if existing.ticket_id != ticket_id or not hmac.compare_digest(existing.request_hash, request_hash):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different decision"},
                )
            await self._ensure_decision_operation(existing)
            return existing
        if int(getattr(card, "version", 0)) != expected_version:
            raise HTTPException(
                status_code=412,
                detail={"code": "VERSION_MISMATCH", "message": "Ticket has changed; reload before deciding", "current_version": int(getattr(card, "version", 0))},
            )
        if card.status != ModerationStatus.IN_REVIEW or card.moderator_id != moderator_id:
            raise HTTPException(status_code=409, detail={"code": "TICKET_NOT_ASSIGNED", "message": "Ticket is not currently assigned to this moderator"})
        self._validate_claim_token(card, claim_token)
        now = datetime.now(timezone.utc)
        expires_at = getattr(card, "lease_expires_at", None)
        if expires_at is None or expires_at <= now:
            raise HTTPException(status_code=409, detail={"code": "LEASE_EXPIRED", "message": "Claim lease expired; claim the ticket again"})
        stored_revision = getattr(card, "submitted_revision", None)
        stored_hash = getattr(card, "snapshot_hash", None)
        if stored_revision is None or not stored_hash:
            raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Ticket has no verified immutable product snapshot"})
        snapshot = await self.repo.session.scalar(
            select(ModerationSnapshot).where(
                ModerationSnapshot.ticket_id == ticket_id,
                ModerationSnapshot.revision == stored_revision,
            )
        )
        if snapshot is None or not hmac.compare_digest(snapshot.snapshot_hash, stored_hash):
            raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Pinned product snapshot is missing or inconsistent"})
        pinned_policy_version = snapshot.content.get("policy_version")
        if type(pinned_policy_version) is not int or pinned_policy_version < 1:
            raise HTTPException(status_code=409, detail={"code": "REVALIDATION_REQUIRED", "message": "Pinned product snapshot has no valid policy version"})
        if snapshot.policy_version is not None and snapshot.policy_version != pinned_policy_version:
            raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_INTEGRITY_FAILURE", "message": "Pinned snapshot policy version does not match its immutable content"})
        if policy_version != pinned_policy_version:
            raise HTTPException(status_code=409, detail={"code": "POLICY_VERSION_MISMATCH", "message": "Decision policy version does not match the pinned snapshot"})
        if stored_revision != product_revision or not hmac.compare_digest(stored_hash, snapshot_hash):
            raise HTTPException(status_code=409, detail={"code": "SNAPSHOT_STALE", "message": "Decision does not match the ticket's pinned product revision"})
        if action == "APPROVE" and not self._has_skus(card):
            raise HTTPException(status_code=409, detail={"code": "APPROVE_REQUIRES_SKU", "message": "Ticket cannot be approved without at least one SKU"})
        if action == "APPROVE" and not passed_rules:
            raise HTTPException(status_code=422, detail={"code": "PASSED_RULES_REQUIRED", "message": "Approval requires at least one recorded passed rule"})
        if action != "APPROVE" and passed_rules:
            raise HTTPException(status_code=422, detail={"code": "PASSED_RULES_NOT_ALLOWED", "message": "Passed rules may only be recorded for approval"})
        if action == "CHANGES_REQUESTED" and not field_reports:
            raise HTTPException(status_code=422, detail={"code": "FIELD_REPORTS_REQUIRED", "message": "Requesting changes requires at least one actionable field report"})
        if action in {"REJECT", "HARD_BLOCK"}:
            if not comment or not comment.strip():
                raise HTTPException(status_code=422, detail={"code": "DECISION_COMMENT_REQUIRED", "message": "Blocking decisions require a non-empty seller-facing comment"})
            if not field_reports:
                raise HTTPException(status_code=422, detail={"code": "FIELD_REPORTS_REQUIRED", "message": "Blocking decisions require at least one field report"})
        all_reason_codes = set(reason_codes or [])
        all_reason_codes.update(str(report.get("reason_code")) for report in field_reports or [] if report.get("reason_code"))
        if action in {"CHANGES_REQUESTED", "REJECT", "HARD_BLOCK"} and not all_reason_codes:
            raise HTTPException(status_code=422, detail={"code": "DECISION_REASON_REQUIRED", "message": "At least one active policy reason is required"})
        if all_reason_codes:
            active_reasons = await self.repo.session.scalars(
                select(BlockingReason).where(
                    BlockingReason.code.in_(all_reason_codes),
                    BlockingReason.is_active.is_(True),
                )
            )
            found_reasons = {reason.code: reason for reason in active_reasons.all()}
            if set(found_reasons) != all_reason_codes:
                raise HTTPException(status_code=422, detail={"code": "DECISION_REASON_INVALID", "message": "A reason code is missing or inactive"})
            if action == "HARD_BLOCK" and not any(reason.hard_block for reason in found_reasons.values()):
                raise HTTPException(status_code=422, detail={"code": "HARD_BLOCK_REASON_REQUIRED", "message": "A hard-block policy reason is required"})

        decision_id = uuid4()
        receipt = ModerationDecisionReceipt(
            id=decision_id,
            ticket_id=ticket_id,
            actor_id=moderator_id,
            idempotency_key=str(idempotency_key),
            request_hash=request_hash,
            action=action,
            product_revision=product_revision,
            snapshot_hash=snapshot_hash,
            policy_version=policy_version,
            reason_codes=sorted(all_reason_codes),
            passed_rules=sorted(passed_rules or []),
            field_reports=field_reports or [],
            comment=comment,
            # The HTTP receipt describes command delivery, not the moderation
            # ticket's internal workflow state. A 202 must never imply that a
            # product is already published or blocked in public projections.
            result_status="DECIDED" if action == "ESCALATE" else "DECISION_PENDING",
        )
        card.status = (
            ModerationStatus.ESCALATED
            if action == "ESCALATE"
            else ModerationStatus.DECISION_PENDING
        )
        card.version = expected_version + 1
        card.updated_at = now
        self.repo.session.add(receipt)
        self.repo.session.add(AdminOperation(
            id=decision_id,
            action="MODERATION_DECISION",
            entity_type="moderation_ticket",
            entity_id=ticket_id,
            payload={
                "decision_id": str(decision_id),
                "product_id": str(card.product_id),
                "submitted_revision": product_revision,
                "action": action,
                "policy_version": policy_version,
            },
            status="APPLIED" if action == "ESCALATE" else "RUNNING",
            version=1,
            idempotency_key=f"moderation:{idempotency_key}",
            request_hash=request_hash,
            requested_by=moderator_id,
            reason_code=(sorted(all_reason_codes) or ["MODERATION_DECISION"])[0],
            updated_at=now,
        ))
        self._audit(
            moderator_id,
            "TICKET_DECISION_" + action,
            ticket_id,
            details={
                "decision_id": str(decision_id),
                "product_revision": product_revision,
                "snapshot_hash": snapshot_hash,
                "policy_version": policy_version,
                "reason_codes": sorted(all_reason_codes),
                "passed_rules": sorted(passed_rules or []),
            },
        )
        if action != "ESCALATE":
            self.repo.session.add(
                ModerationOutboxEvent(
                    id=decision_id,
                    idempotency_key=str(idempotency_key),
                    event_type="MODERATION_DECISION",
                    payload={
                        "decision_id": str(decision_id),
                        "product_id": str(card.product_id),
                        "seller_id": str(card.seller_id) if card.seller_id else None,
                        "submitted_revision": product_revision,
                        "snapshot_hash": snapshot_hash,
                        "policy_version": policy_version,
                        "action": action,
                        "reason_codes": reason_codes or [],
                        "field_reports": field_reports or [],
                        "correlation_id": str(idempotency_key),
                    },
                )
            )
        try:
            await self.repo.session.flush()
        except IntegrityError:
            # The actor/key uniqueness constraint is the final guard when the
            # same idempotency key races on two ticket rows.
            await self.repo.session.rollback()
            raced = await self.repo.session.scalar(
                select(ModerationDecisionReceipt).where(
                    ModerationDecisionReceipt.actor_id == moderator_id,
                    ModerationDecisionReceipt.idempotency_key == str(idempotency_key),
                )
            )
            if raced is None:
                raise
            if raced.ticket_id != ticket_id or not hmac.compare_digest(raced.request_hash, request_hash):
                raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different decision"})
            await self._ensure_decision_operation(raced)
            return raced
        return receipt

    def _validate_claim_token(self, card: object, claim_token: str) -> None:
        stored_hash = getattr(card, "lease_token_hash", None)
        supplied_hash = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
        if not stored_hash or not hmac.compare_digest(stored_hash, supplied_hash):
            raise HTTPException(status_code=409, detail={"code": "INVALID_CLAIM_TOKEN", "message": "Claim token is invalid or has been fenced by a newer claim"})

    async def approve_product(self, card_id: UUID, moderator_id: UUID):
        card = await self._get_mutable_card(card_id, moderator_id)
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVE_NOT_ALLOWED",
                    "message": "Ticket cannot be approved in current status",
                    "current_status": self._status_value(card.status),
                },
            )
        if not self._has_skus(card):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVE_REQUIRES_SKU",
                    "message": "Ticket cannot be approved without SKU",
                },
            )

        card.status = ModerationStatus.MODERATED
        self._audit(moderator_id, "TICKET_APPROVE", card.id)
        await self._enqueue_decision(self._moderated_event(card))
        await self.repo.session.flush()
        return card

    async def block_product(
        self,
        card_id: UUID,
        moderator_id: UUID,
        *,
        blocking_reason_ids: list[UUID],
        comment: str | None = None,
        field_reports: list[FieldReport] | None = None,
    ):
        card = await self._get_mutable_card(card_id, moderator_id)
        if card.status != ModerationStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BLOCK_NOT_ALLOWED",
                    "message": "Ticket cannot be blocked in current status",
                    "current_status": self._status_value(card.status),
                },
            )

        reasons = await self.repo.list_blocking_reasons(blocking_reason_ids)
        found_ids = {reason.id for reason in reasons}
        missing_ids = [
            str(reason_id)
            for reason_id in blocking_reason_ids
            if reason_id not in found_ids
        ]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "BLOCKING_REASON_NOT_FOUND",
                    "message": "Blocking reason not found",
                    "blocking_reason_ids": missing_ids,
                },
            )

        selected_reason = next(
            reason for reason in reasons if reason.id == blocking_reason_ids[0]
        )

        return await self._block_card(
            card,
            hard_block=any(reason.hard_block for reason in reasons),
            blocking_reason=selected_reason,
            comment=comment,
            field_reports=field_reports or [],
        )

    async def _block_card(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason: object | None,
        comment: str | None,
        field_reports: list[FieldReport],
    ):
        card.status = (
            ModerationStatus.HARD_BLOCKED if hard_block else ModerationStatus.BLOCKED
        )
        self._audit(getattr(card, "moderator_id", None), "TICKET_BLOCK", card.id)
        await self._enqueue_decision(
            self._blocked_event(
                card,
                hard_block=hard_block,
                blocking_reason=blocking_reason,
                comment=comment,
                field_reports=field_reports or [],
            )
        )
        await self.repo.session.flush()
        return card

    async def _enqueue_decision(self, event: dict[str, object]) -> None:
        add = getattr(self.repo.session, "add", None)
        if not callable(add):
            await B2BClient().send_moderation_decision(event)
            return
        add(
            ModerationOutboxEvent(
                idempotency_key=str(event["idempotency_key"]),
                event_type=str(event["event_type"]),
                payload=event,
            )
        )

    async def retry_pending_decisions(self, limit: int = 100) -> int:
        """Lease in a short transaction, deliver outside row locks, then ack by CAS."""
        now = datetime.now(timezone.utc)
        worker_id = f"admin-outbox-{uuid4()}"
        request_timeout = settings.b2b_timeout_seconds
        lease_seconds = max(60, math.ceil(request_timeout * 2))
        lease_safe_limit = max(1, int(lease_seconds // (request_timeout * 2)))
        events = await self.claim_pending_decisions(
            worker_id=worker_id,
            limit=min(max(1, limit), lease_safe_limit),
            lease_seconds=lease_seconds,
        )
        await self.repo.session.commit()
        delivered = 0
        for event in events:
            attempts = event.attempts + 1
            values: dict[str, object] = {
                "attempts": attempts,
                "lease_owner": None,
                "lease_until": None,
            }
            if attempts > self.MAX_OUTBOX_ATTEMPTS:
                values.update(status="DEAD", last_error="OUTBOX_MAX_ATTEMPTS_EXCEEDED")
                await self.repo.session.execute(
                    update(ModerationOutboxEvent)
                    .where(ModerationOutboxEvent.id == event.id, ModerationOutboxEvent.lease_owner == worker_id)
                    .values(**values)
                )
                if event.event_type in {"TAXONOMY_COMMAND", "B2B_COMMAND"} and event.payload.get("operation_id"):
                    command = event.payload.get("command")
                    aggregate_id = command.get("aggregate_id") if isinstance(command, dict) else None
                    await self.repo.session.execute(
                        update(AdminOperation)
                        .where(AdminOperation.id == UUID(str(event.payload["operation_id"])), AdminOperation.status == "QUEUED")
                        .values(status="FAILED", version=AdminOperation.version + 1, updated_at=now)
                    )
                    if aggregate_id:
                        self.repo.session.add(AuditLog(
                            actor_id=None,
                            action=f"{event.event_type}_FAILED",
                            entity_type=str(event.payload.get("entity_type") or "category"),
                            entity_id=UUID(str(aggregate_id)),
                            details={"operation_id": str(event.payload["operation_id"]), "command_id": str(command.get("command_id")), "outcome": "MAX_ATTEMPTS"},
                            created_at=now,
                        ))
                elif event.event_type == "MODERATION_DECISION":
                    await self.repo.session.execute(
                        update(AdminOperation)
                        .where(
                            AdminOperation.id == event.id,
                            AdminOperation.action == "MODERATION_DECISION",
                            AdminOperation.status == "RUNNING",
                        )
                        .values(
                            status="FAILED",
                            version=AdminOperation.version + 1,
                            updated_at=now,
                        )
                    )
                await self.repo.session.commit()
                continue
            try:
                if event.event_type == "TAXONOMY_COMMAND":
                    command = event.payload.get("command")
                    if not isinstance(command, dict):
                        raise HTTPException(status_code=422, detail={"code": "INVALID_TAXONOMY_COMMAND", "message": "Stored taxonomy command is invalid"})
                    client = B2BClient()
                    if event.payload.get("awaiting_ack") is True:
                        receipt = await client.get_taxonomy_command(str(command["command_id"]))
                    else:
                        receipt = await client.submit_taxonomy_command(command)
                    receipt_status = str(receipt["status"])
                    if receipt_status == "APPLIED":
                        values.update(status="SENT", last_error=None, next_retry_at=None)
                        event.payload = {**event.payload, "awaiting_ack": False}
                        if event.payload.get("operation_id"):
                            operation_id = UUID(str(event.payload["operation_id"]))
                            await self.repo.session.execute(
                                update(AdminOperation)
                                .where(AdminOperation.id == operation_id, AdminOperation.status == "QUEUED")
                                .values(status="APPLIED", version=AdminOperation.version + 1, updated_at=now)
                            )
                            command = event.payload.get("command")
                            aggregate_id = command.get("aggregate_id") if isinstance(command, dict) else None
                            if aggregate_id:
                                self.repo.session.add(AuditLog(
                                    actor_id=None,
                                    action="TAXONOMY_COMMAND_APPLIED",
                                    entity_type=str(event.payload.get("entity_type") or "category"),
                                    entity_id=UUID(str(aggregate_id)),
                                    details={"operation_id": str(operation_id), "command_id": str(command.get("command_id"))},
                                    created_at=now,
                                ))
                        delivered += 1
                    elif receipt_status == "QUEUED":
                        values.update(
                            status="WAITING_ACK", attempts=attempts,
                            last_error=None, next_retry_at=now + timedelta(seconds=5),
                        )
                        event.payload = {**event.payload, "awaiting_ack": True}
                    else:
                        values.update(status="DEAD", last_error=f"B2B_COMMAND_{receipt_status}", next_retry_at=None)
                        if event.payload.get("operation_id"):
                            operation_id = UUID(str(event.payload["operation_id"]))
                            await self.repo.session.execute(
                                update(AdminOperation)
                                .where(AdminOperation.id == operation_id, AdminOperation.status == "QUEUED")
                                .values(status="FAILED", version=AdminOperation.version + 1, updated_at=now)
                            )
                            command = event.payload.get("command")
                            aggregate_id = command.get("aggregate_id") if isinstance(command, dict) else None
                            if aggregate_id:
                                self.repo.session.add(AuditLog(
                                    actor_id=None,
                                    action="TAXONOMY_COMMAND_FAILED",
                                    entity_type=str(event.payload.get("entity_type") or "category"),
                                    entity_id=UUID(str(aggregate_id)),
                                    details={"operation_id": str(operation_id), "command_id": str(command.get("command_id")), "outcome": receipt_status},
                                    created_at=now,
                                ))
                elif event.event_type == "B2B_COMMAND":
                    command = event.payload.get("command")
                    if not isinstance(command, dict):
                        raise HTTPException(status_code=422, detail={"code": "INVALID_ADMIN_COMMAND", "message": "Stored Admin command is invalid"})
                    receipt = await B2BClient().submit_safety_command(command)
                    receipt_status = str(receipt["status"])
                    if receipt_status == "APPLIED":
                        values.update(status="SENT", last_error=None, next_retry_at=None)
                        event.payload = {**event.payload, "awaiting_ack": False}
                        operation_id = UUID(str(event.payload["operation_id"])) if event.payload.get("operation_id") else None
                        if operation_id is not None:
                            await self.repo.session.execute(
                                update(AdminOperation)
                                .where(AdminOperation.id == operation_id, AdminOperation.status == "QUEUED")
                                .values(status="APPLIED", version=AdminOperation.version + 1, updated_at=now)
                            )
                            self.repo.session.add(AuditLog(
                                actor_id=None, action="ADMIN_COMMAND_APPLIED",
                                entity_type=str(event.payload.get("entity_type") or "product"),
                                entity_id=UUID(str(command["aggregate_id"])),
                                details={"operation_id": str(operation_id), "command_id": str(command["command_id"])},
                                created_at=now,
                            ))
                        delivered += 1
                    elif receipt_status == "QUEUED":
                        # The internal contract has no receipt GET for these commands.
                        # Repeating the same POST is the idempotent receipt poll.
                        values.update(
                            status="WAITING_ACK", attempts=attempts,
                            last_error=None, next_retry_at=now + timedelta(seconds=5),
                        )
                        event.payload = {**event.payload, "awaiting_ack": True}
                    else:
                        values.update(status="DEAD", last_error=f"B2B_COMMAND_{receipt_status}", next_retry_at=None)
                        if event.payload.get("operation_id"):
                            await self.repo.session.execute(
                                update(AdminOperation)
                                .where(AdminOperation.id == UUID(str(event.payload["operation_id"])), AdminOperation.status == "QUEUED")
                                .values(status="FAILED", version=AdminOperation.version + 1, updated_at=now)
                            )
                            self.repo.session.add(AuditLog(
                                actor_id=None, action="ADMIN_COMMAND_FAILED",
                                entity_type=str(event.payload.get("entity_type") or "product"),
                                entity_id=UUID(str(command["aggregate_id"])),
                                details={"operation_id": str(event.payload["operation_id"]), "command_id": str(command["command_id"]), "outcome": receipt_status},
                                created_at=now,
                            ))
                else:
                    await B2BClient().send_moderation_decision(event.payload)
                    # A successful HTTP response confirms receipt only. The
                    # decision remains pending until B2B returns a durable
                    # publication result event.
                    values.update(
                        status="WAITING_ACK",
                        attempts=attempts,
                        last_error=None,
                        next_retry_at=now + timedelta(seconds=30),
                    )
                    await self.repo.session.execute(
                        update(AdminOperation)
                        .where(
                            AdminOperation.id == event.id,
                            AdminOperation.action == "MODERATION_DECISION",
                            AdminOperation.status.in_(["FAILED", "PARTIAL"]),
                        )
                        .values(
                            status="RUNNING",
                            version=AdminOperation.version + 1,
                            updated_at=now,
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - retain event for retry
                code = getattr(exc, "status_code", None)
                if event.event_type in {"TAXONOMY_COMMAND", "B2B_COMMAND"} and code is not None and 400 <= code < 500 and code != 429:
                    values.update(status="DEAD", last_error="B2B_COMMAND_REJECTED", next_retry_at=None)
                    if event.payload.get("operation_id"):
                        await self.repo.session.execute(
                            update(AdminOperation)
                            .where(AdminOperation.id == UUID(str(event.payload["operation_id"])), AdminOperation.status == "QUEUED")
                            .values(status="FAILED", version=AdminOperation.version + 1, updated_at=now)
                        )
                        command = event.payload.get("command")
                        aggregate_id = command.get("aggregate_id") if isinstance(command, dict) else None
                        if aggregate_id:
                            self.repo.session.add(AuditLog(
                                actor_id=None,
                                action="ADMIN_COMMAND_FAILED" if event.event_type == "B2B_COMMAND" else "TAXONOMY_COMMAND_FAILED",
                                entity_type=str(event.payload.get("entity_type") or "category"),
                                entity_id=UUID(str(aggregate_id)),
                                details={"operation_id": str(event.payload["operation_id"]), "command_id": str(command.get("command_id")), "outcome": "REJECTED"},
                                created_at=now,
                            ))
                else:
                    values.update(
                        status="RETRY",
                        last_error="B2B_DELIVERY_FAILED",
                        next_retry_at=now + timedelta(seconds=min(900, 2 ** min(attempts, 10))),
                    )
            await self.repo.session.execute(
                update(ModerationOutboxEvent)
                .where(ModerationOutboxEvent.id == event.id, ModerationOutboxEvent.lease_owner == worker_id)
                .values(**values)
            )
            await self.repo.session.commit()
        return delivered

    async def claim_pending_decisions(
        self, *, worker_id: str = "admin-moderation-outbox", limit: int = 100, lease_seconds: int = 60
    ) -> list[ModerationOutboxEvent]:
        """Claim ready events with row locks so concurrent workers do not duplicate delivery."""
        if not hasattr(self.repo.session, "execute"):
            return []
        now = datetime.now(timezone.utc)
        result = await self.repo.session.execute(
            select(ModerationOutboxEvent)
            .where(
                ModerationOutboxEvent.status.in_(["PENDING", "RETRY", "LEASED", "WAITING_ACK"]),
                (ModerationOutboxEvent.next_retry_at.is_(None)
                 | (ModerationOutboxEvent.next_retry_at <= now)),
                (ModerationOutboxEvent.lease_until.is_(None)
                 | (ModerationOutboxEvent.lease_until < now)),
            )
            .order_by(ModerationOutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(result.scalars().all())
        lease_until = now + timedelta(seconds=lease_seconds)
        for event in events:
            event.status = "LEASED"
            event.lease_owner = worker_id
            event.lease_until = lease_until
        await self.repo.session.flush()
        return events

    async def apply_publication_decision_event(
        self, event: PublicationDecisionEnvelope
    ) -> dict[str, str]:
        event_data = event.model_dump(mode="json")
        payload_hash = hashlib.sha256(
            json.dumps(event_data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        stored_event = await self.repo.session.scalar(
            select(ProcessedProductEvent)
            .where(ProcessedProductEvent.event_id == event.event_id)
            .with_for_update()
        )
        if stored_event is not None:
            if stored_event.payload_sha256 != payload_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "EVENT_ID_CONFLICT",
                        "message": "event_id was reused with different payload",
                    },
                )
            return {"status": "ALREADY_APPLIED"}

        payload = event.payload
        decision = await self.repo.session.scalar(
            select(ModerationDecisionReceipt)
            .where(ModerationDecisionReceipt.id == payload.decision_id)
            .with_for_update()
        )
        outbox_event = await self.repo.session.scalar(
            select(ModerationOutboxEvent)
            .where(ModerationOutboxEvent.id == payload.decision_id)
            .with_for_update()
        )
        if decision is None or outbox_event is None or outbox_event.event_type != "MODERATION_DECISION":
            raise HTTPException(
                status_code=404,
                detail={"code": "DECISION_NOT_FOUND", "message": "Moderation decision was not found"},
            )
        if (
            decision.ticket_id is None
            or str(decision.idempotency_key) != str(event.correlation_id)
            or decision.action != payload.action
            or decision.product_revision != payload.submitted_revision
            or str(outbox_event.payload.get("product_id")) != str(payload.product_id)
            or str(outbox_event.payload.get("correlation_id")) != str(event.correlation_id)
            or str(outbox_event.payload.get("submitted_revision")) != str(payload.submitted_revision)
            or str(outbox_event.payload.get("action")) != payload.action
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "DECISION_RECEIPT_MISMATCH", "message": "B2B result does not match the recorded decision"},
            )
        card = await self.repo.session.scalar(
            select(ModerationCard)
            .where(ModerationCard.id == decision.ticket_id)
            .with_for_update()
        )
        if card is None or card.product_id != payload.product_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "DECISION_TICKET_MISMATCH", "message": "B2B result does not match the recorded ticket"},
            )

        applied = event.event_type == "product.publication.applied.v1"
        if applied and payload.action == "APPROVE" and payload.published_revision != payload.submitted_revision:
            raise HTTPException(
                status_code=409,
                detail={"code": "PUBLICATION_REVISION_MISMATCH", "message": "B2B did not publish the approved revision"},
            )
        if card.status not in {ModerationStatus.DECISION_PENDING, ModerationStatus.STALE}:
            raise HTTPException(
                status_code=409,
                detail={"code": "DECISION_STATE_MISMATCH", "message": "Ticket is no longer waiting for its B2B result"},
            )
        ticket_already_stale = card.status == ModerationStatus.STALE

        receipt = ProcessedProductEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            payload_sha256=payload_hash,
        )
        self.repo.session.add(receipt)
        try:
            await self.repo.session.flush()
        except IntegrityError as exc:
            await self.repo.session.rollback()
            raced = await self.repo.session.get(ProcessedProductEvent, event.event_id)
            if raced is not None and raced.payload_sha256 == payload_hash:
                return {"status": "ALREADY_APPLIED"}
            raise HTTPException(
                status_code=409,
                detail={"code": "EVENT_ID_CONFLICT", "message": "event_id was reused with different payload"},
            ) from exc

        now = datetime.now(timezone.utc)
        if applied:
            if not ticket_already_stale:
                card.status = {
                    "APPROVE": ModerationStatus.MODERATED,
                    "CHANGES_REQUESTED": ModerationStatus.WAITING_SELLER,
                    "REJECT": ModerationStatus.BLOCKED,
                    "HARD_BLOCK": ModerationStatus.HARD_BLOCKED,
                }[payload.action]
            outbox_event.status = "SENT"
            outbox_event.last_error = None
            outbox_event.next_retry_at = None
            result = "APPLIED"
            action_name = (
                "MODERATION_DECISION_APPLIED_AFTER_STALE"
                if ticket_already_stale
                else "MODERATION_DECISION_APPLIED"
            )
        else:
            card.status = ModerationStatus.STALE
            card.moderator_id = None
            card.lease_token_hash = None
            card.lease_expires_at = None
            outbox_event.status = "BLOCKED"
            outbox_event.last_error = (payload.reason_code or "B2B_DECISION_REJECTED")[:500]
            outbox_event.next_retry_at = None
            result = "REJECTED"
            action_name = "MODERATION_DECISION_REJECTED"
        card.version += 1
        card.updated_at = now
        outbox_event.lease_owner = None
        outbox_event.lease_until = None
        decision_operation = await self.repo.session.scalar(
            select(AdminOperation)
            .where(AdminOperation.id == decision.id)
            .with_for_update()
        )
        operation_status = "APPLIED" if applied else "FAILED"
        if decision_operation is None:
            await self._ensure_decision_operation(
                decision, status_value=operation_status
            )
        elif decision_operation.action != "MODERATION_DECISION":
            raise HTTPException(
                status_code=409,
                detail={"code": "OPERATION_ID_CONFLICT", "message": "Decision operation ID is already in use"},
            )
        elif decision_operation.status != operation_status:
            decision_operation.status = operation_status
            decision_operation.version += 1
            decision_operation.updated_at = now
        self._audit(
            None,
            action_name,
            card.id,
            details={
                "decision_id": str(decision.id),
                "product_id": str(payload.product_id),
                "submitted_revision": payload.submitted_revision,
                "action": payload.action,
                "published_revision": payload.published_revision,
                "visible": payload.visible,
                "reason_code": payload.reason_code,
                "ticket_was_stale": ticket_already_stale,
            },
        )
        await self.repo.session.flush()
        return {"status": result}

    async def apply_product_event(self, event: dict[str, object]) -> dict[str, str]:
        raw_event_id = str(event.get("event_id") or event.get("idempotency_key"))
        try:
            event_id = UUID(raw_event_id)
        except ValueError:
            event_id = uuid5(
                NAMESPACE_URL,
                f"admin-product-event:{raw_event_id}:{event.get('event_type')}:{event.get('product_id')}",
            )
        receipt = ProcessedProductEvent(
            event_id=event_id,
            event_type=str(event.get("event_type", "")),
            payload_sha256=hashlib.sha256(
                json.dumps(event, default=str, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        if hasattr(self.repo.session, "execute"):
            existing = await self.repo.session.execute(
                select(ProcessedProductEvent).where(ProcessedProductEvent.event_id == event_id)
            )
            stored = existing.scalar_one_or_none()
            if stored is not None:
                if stored.payload_sha256 != receipt.payload_sha256:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "EVENT_ID_CONFLICT",
                            "message": "event_id was reused with different payload",
                        },
                    )
                return {"status": "ALREADY_APPLIED"}
        add_receipt = getattr(self.repo.session, "add", None)
        if callable(add_receipt):
            add_receipt(receipt)
            try:
                await self.repo.session.flush()
            except IntegrityError:
                await self.repo.session.rollback()
                stored = await self.repo.session.scalar(
                    select(ProcessedProductEvent).where(
                        ProcessedProductEvent.event_id == receipt.event_id
                    )
                )
                if stored is not None and stored.payload_sha256 != receipt.payload_sha256:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "EVENT_ID_CONFLICT", "message": "event_id was reused with different payload"},
                    )
                return {"status": "ALREADY_APPLIED"}
        product_id = UUID(str(event["product_id"]))
        card = await self.repo.get_by_product_id_for_update(product_id)
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        raw_snapshot = payload.get("json_after") or payload.get("content") or payload
        snapshot_content = raw_snapshot if isinstance(raw_snapshot, dict) else {}
        raw_revision = (
            event.get("aggregate_version")
            or payload.get("revision")
            or payload.get("product_revision")
            or snapshot_content.get("revision")
            or snapshot_content.get("product_revision")
        )
        try:
            revision = int(raw_revision) if raw_revision is not None else None
        except (ValueError, TypeError):
            revision = None

        if event_type.endswith(("CREATED", "EDITED")) and revision is not None and revision >= 1:
            if card is not None and card.submitted_revision is not None and revision <= card.submitted_revision:
                return {"status": "STALE_EVENT"}
            if card is not None and card.status in {
                ModerationStatus.CREATED,
                ModerationStatus.PENDING,
                ModerationStatus.IN_REVIEW,
                ModerationStatus.DECISION_PENDING,
                ModerationStatus.WAITING_SELLER,
                ModerationStatus.ESCALATED,
            }:
                card.status = ModerationStatus.STALE
                card.moderator_id = None
                card.lease_token_hash = None
                card.lease_expires_at = None
                card.version += 1
            content_hash = content_digest(snapshot_content)
            raw_source_hash = event.get("snapshot_hash") or payload.get("snapshot_hash") or snapshot_content.get("snapshot_hash")
            if raw_source_hash is None:
                snapshot_hash = content_hash
            else:
                try:
                    snapshot_hash = normalize_source_digest(raw_source_hash)
                except ValueError:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE_SNAPSHOT_HASH", "message": "B2B product event contains an invalid snapshot hash"})
            raw_media_refs = payload.get("media_refs", snapshot_content.get("media_refs", []))
            if not isinstance(raw_media_refs, list) or any(not isinstance(item, str) for item in raw_media_refs):
                raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE_MEDIA_REFS", "message": "B2B product event contains invalid media references"})
            new_card = ModerationCard(
                product_id=product_id,
                seller_id=UUID(str(event.get("seller_id") or payload.get("seller_id") or snapshot_content.get("seller_id")))
                if event.get("seller_id") or payload.get("seller_id") or snapshot_content.get("seller_id")
                else None,
                kind="CREATE" if event_type.endswith("CREATED") else "UPDATE",
                queue_priority=3 if event_type.endswith("CREATED") else 4,
                status=ModerationStatus.PENDING,
                submitted_revision=revision,
                snapshot_hash=snapshot_hash,
                version=1,
                fencing_version=0,
            )
            self.repo.session.add(new_card)
            await self.repo.session.flush()
            self.repo.session.add(
                ModerationSnapshot(
                    ticket_id=new_card.id,
                    revision=revision,
                    policy_version=snapshot_content.get("policy_version") if type(snapshot_content.get("policy_version")) is int else None,
                    snapshot_hash=snapshot_hash,
                    content_hash=content_hash,
                    content=snapshot_content,
                    media_refs=raw_media_refs,
                )
            )
            raw_skus = snapshot_content.get("skus", [])
            if isinstance(raw_skus, list):
                for sku in raw_skus:
                    if not isinstance(sku, dict) or not sku.get("id"):
                        continue
                    try:
                        sku_id = UUID(str(sku["id"]))
                    except ValueError:
                        continue
                    self.repo.session.add(
                        ModerationSKU(
                            card_id=new_card.id,
                            sku_id=sku_id,
                            name=str(sku.get("name") or "")[:255],
                        )
                    )
            self._audit(None, "PRODUCT_REVISION_RECEIVED", new_card.id)
            await self.repo.session.flush()
            return {"status": "TICKET_CREATED", "ticket_id": str(new_card.id)}

        if not card:
            return {"status": "IGNORED"}

        if event_type.endswith("DELETED"):
            self._audit(None, "PRODUCT_EVENT_DELETED", card.id)
            card.status = ModerationStatus.CANCELLED
            card.moderator_id = None
            card.lease_token_hash = None
            card.lease_expires_at = None
            card.version += 1
            return {"status": "CANCELLED"}
        if card.status == ModerationStatus.HARD_BLOCKED:
            return {"status": "IGNORED"}
        if event_type.endswith("EDITED"):
            self._audit(None, "PRODUCT_EVENT_EDITED", card.id)
            card.status = ModerationStatus.PENDING
            card.moderator_id = None
            card.lease_token_hash = None
            card.lease_expires_at = None
            card.queue_priority = self._edited_queue_priority(card)
            card.version += 1
            await self.repo.session.flush()
            return {"status": "UPDATED"}
        return {"status": "IGNORED"}

    async def _get_mutable_card(self, card_id: UUID, moderator_id: UUID):
        card = await self.repo.get_with_skus(card_id)
        if not card:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Moderation card not found",
            )
        if card.moderator_id != moderator_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "TICKET_NOT_ASSIGNED",
                    "message": "Ticket is assigned to another moderator",
                },
            )
        if card.status == ModerationStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "HARD_BLOCKED_TERMINAL",
                    "message": "Hard blocked ticket cannot be modified",
                    "current_status": "HARD_BLOCKED",
                },
            )
        return card

    def _moderated_event(self, card: object) -> dict[str, object]:
        product_id = str(card.product_id)
        return {
            "idempotency_key": str(uuid4()),
            "event_type": "MODERATED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

    def _blocked_event(
        self,
        card: object,
        *,
        hard_block: bool,
        blocking_reason: object | None,
        comment: str | None,
        field_reports: list[FieldReport],
    ) -> dict[str, object]:
        product_id = str(card.product_id)
        serialized_reports = [report.model_dump(mode="json") for report in field_reports]
        return {
            # Retries reuse the same payload/key; a later decision gets a new
            # key even when it targets the same product.
            "idempotency_key": str(uuid4()),
            "event_type": "BLOCKED",
            "product_id": product_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "hard_block": hard_block,
            "blocking_reason_id": str(blocking_reason.id)
            if blocking_reason is not None
            else None,
            "moderator_comment": comment
            or getattr(blocking_reason, "description", None)
            or self._first_field_report_comment(serialized_reports),
            "field_reports": serialized_reports,
        }

    def _first_field_report_comment(
        self,
        field_reports: list[dict[str, object]],
    ) -> str | None:
        for report in field_reports:
            if isinstance(report, dict) and report.get("comment"):
                return str(report["comment"])
        return None

    def _has_skus(self, card: object) -> bool:
        if hasattr(card, "sku_ids"):
            return bool(card.sku_ids)
        return bool(getattr(card, "skus", []))

    def _edited_queue_priority(self, card: object) -> int:
        return max(int(getattr(card, "queue_priority", 0)), 0) + 1

    def _audit(
        self,
        actor_id: UUID | None,
        action: str,
        entity_id: UUID,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        add = getattr(self.repo.session, "add", None)
        if add is not None:
            add(
                AuditLog(
                    actor_id=actor_id,
                    action=action,
                    entity_type="moderation_ticket",
                    entity_id=entity_id,
                    details=details or {},
                    created_at=datetime.now(timezone.utc),
                )
            )

    def _status_value(self, value: object) -> str:
        return value.value if isinstance(value, ModerationStatus) else str(value)
