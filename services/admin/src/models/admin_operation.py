import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdminOperation(Base):
    __tablename__ = "admin_operations"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_admin_operation_actor_key"),
        UniqueConstraint("approval_key", name="uq_admin_operation_approval_key"),
        UniqueConstraint("cancel_key", name="uq_admin_operation_cancel_key"),
        Index("ix_admin_operations_status_created", "status", "created_at", "id"),
        Index("ix_admin_operations_created_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="WAITING_APPROVAL", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=True
    )
    approval_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=True
    )
    cancel_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
