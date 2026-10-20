import re
import uuid

from sqlalchemy import BigInteger, JSON, CheckConstraint, DateTime, SmallInteger, String, UniqueConstraint, event, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base
from src.services.audit_context import current_audit_context


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("sequence_no", name="uq_audit_logs_sequence_no"),
        UniqueConstraint("integrity_hash", name="uq_audit_logs_integrity_hash"),
        CheckConstraint("integrity_version IN (1, 2)", name="ck_audit_logs_integrity_version"),
        CheckConstraint(
            "integrity_version = 1 OR actor_roles IS NOT NULL",
            name="ck_audit_logs_v2_actor_roles_present",
        ),
        CheckConstraint(
            "actor_roles IS NULL OR jsonb_typeof(actor_roles::jsonb) = 'array'",
            name="ck_audit_logs_actor_roles_array",
        ),
        CheckConstraint(
            "before_hash IS NULL OR before_hash ~ '^[A-Fa-f0-9]{64}$'",
            name="ck_audit_logs_before_hash_format",
        ),
        CheckConstraint(
            "after_hash IS NULL OR after_hash ~ '^[A-Fa-f0-9]{64}$'",
            name="ck_audit_logs_after_hash_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2, server_default=text("2"))
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)


@event.listens_for(AuditLog, "before_insert")
def populate_structured_audit_context(mapper, connection, target: AuditLog) -> None:
    context = current_audit_context()
    details = target.details if isinstance(target.details, dict) else {}
    if target.integrity_version is None:
        target.integrity_version = 2
    if target.actor_id is None and context.actor_id is not None:
        target.actor_id = context.actor_id
    if target.request_id is None:
        target.request_id = context.request_id
    if target.correlation_id is None:
        correlation_id = details.get("correlation_id")
        target.correlation_id = (
            correlation_id
            if isinstance(correlation_id, str) and len(correlation_id) <= 128
            else context.correlation_id
        )
    if target.actor_roles is None:
        target.actor_roles = list(context.actor_roles)
    if not isinstance(target.actor_roles, list) or any(
        not isinstance(role, str) or not role.strip() or len(role) > 64
        for role in target.actor_roles
    ):
        raise ValueError("audit actor_roles must be a list of non-empty strings up to 64 characters")
    if target.reason_code is None:
        reason_code = details.get("reason_code")
        if isinstance(reason_code, str) and len(reason_code) <= 64:
            target.reason_code = reason_code
    for field_name in ("before_hash", "after_hash"):
        value = getattr(target, field_name)
        if value is None:
            candidate = details.get(field_name)
            if isinstance(candidate, str) and re.fullmatch(r"[a-fA-F0-9]{64}", candidate):
                setattr(target, field_name, candidate.lower())
