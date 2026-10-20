import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Appeal(Base):
    __tablename__ = "admin_appeals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUBMITTED','TRIAGED','IN_REVIEW','UPHELD','OVERTURNED','PARTIALLY_UPHELD','CLOSED')",
            name="ck_admin_appeal_status",
        ),
        CheckConstraint("claimant_ref ~ '^[a-fA-F0-9]{64}$'", name="ck_admin_appeal_claimant_ref"),
        CheckConstraint("version >= 1", name="ck_admin_appeal_version"),
        Index("ix_admin_appeals_status_created", "status", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    original_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("moderation_decision_receipts.id", ondelete="RESTRICT"), nullable=False
    )
    claimant_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reviewer_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="SUBMITTED", nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AppealDecision(Base):
    __tablename__ = "admin_appeal_decisions"
    __table_args__ = (
        CheckConstraint("outcome IN ('UPHELD','OVERTURNED','PARTIALLY_UPHELD')", name="ck_admin_appeal_outcome"),
        CheckConstraint("reason_code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_admin_appeal_decision_reason"),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name="ck_admin_appeal_decision_hash"),
        UniqueConstraint("reviewer_staff_id", "idempotency_key", name="uq_admin_appeal_reviewer_key"),
        UniqueConstraint("appeal_id", name="uq_admin_appeal_single_decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appeal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_appeals.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
