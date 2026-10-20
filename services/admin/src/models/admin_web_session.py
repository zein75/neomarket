import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdminWebSession(Base):
    __tablename__ = "admin_web_sessions"
    __table_args__ = (
        Index("ix_admin_web_sessions_principal", "principal_id", "revoked_at"),
        Index("ix_admin_web_sessions_expiry", "idle_expires_at", "absolute_expires_at"),
        UniqueConstraint("oidc_jti_hash", name="uq_admin_web_sessions_oidc_jti_hash"),
        CheckConstraint(
            "oidc_jti_hash IS NULL OR oidc_token_expires_at IS NOT NULL",
            name="ck_admin_web_session_jti_expiry",
        ),
        CheckConstraint(
            "step_up_expires_at IS NULL OR step_up_expires_at <= absolute_expires_at",
            name="ck_admin_web_session_step_up_expiry",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oidc_jti_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oidc_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    step_up_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
