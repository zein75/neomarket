import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdminOidcTokenReceipt(Base):
    __tablename__ = "admin_oidc_token_receipts"
    __table_args__ = (
        Index("ix_admin_oidc_token_receipts_expiry", "expires_at"),
        UniqueConstraint("jti_hash", name="uq_admin_oidc_token_receipts_jti_hash"),
        CheckConstraint("purpose IN ('SESSION_EXCHANGE', 'STEP_UP')", name="ck_admin_oidc_receipt_purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
