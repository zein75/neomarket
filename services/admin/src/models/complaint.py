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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Complaint(Base):
    __tablename__ = "admin_complaints"
    __table_args__ = (
        CheckConstraint("source IN ('B2C','SELLER','ADMIN')", name="ck_admin_complaint_source"),
        CheckConstraint("reporter_ref ~ '^[a-fA-F0-9]{64}$'", name="ck_admin_complaint_reporter_ref"),
        CheckConstraint("entity_type IN ('PRODUCT','SELLER','MEDIA')", name="ck_admin_complaint_entity_type"),
        CheckConstraint("status IN ('NEW','TRIAGED','IN_REVIEW','CLOSED','ESCALATED')", name="ck_admin_complaint_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_admin_complaint_priority"),
        CheckConstraint("version >= 1", name="ck_admin_complaint_version"),
        Index("ix_admin_complaints_status_priority_created", "status", "priority", "created_at", "id"),
        Index("ix_admin_complaints_status_deadline", "status", "deadline_at"),
        Index(
            "ix_admin_complaints_queue_order",
            text("priority DESC"),
            text("created_at ASC"),
            text("id ASC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reporter_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="NEW", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ComplaintAction(Base):
    __tablename__ = "admin_complaint_actions"
    __table_args__ = (
        CheckConstraint("action IN ('ASSIGN','REQUEST_INFO','WARN','TEMP_HOLD','UNPUBLISH','CLOSE','ESCALATE')", name="ck_admin_complaint_action_type"),
        CheckConstraint("reason_code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_admin_complaint_action_reason"),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name="ck_admin_complaint_action_hash"),
        Index("ix_admin_complaint_actions_complaint_created", "complaint_id", "created_at"),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_admin_complaint_actor_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_complaints.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
