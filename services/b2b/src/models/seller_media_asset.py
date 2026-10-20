import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SellerMediaAsset(Base, TimestampMixin):
    __tablename__ = "seller_media_assets"
    __table_args__ = (
        UniqueConstraint("seller_id", "idempotency_key", name="uq_seller_media_idempotency"),
        Index("ix_seller_media_assets_scan_queue", "state", "updated_at"),
        CheckConstraint(
            "state IN ('UPLOAD_PENDING', 'UPLOADED', 'SCAN_QUEUED', 'SCANNING', 'READY', 'REJECTED', 'EXPIRED')",
            name="ck_seller_media_state",
        ),
        CheckConstraint("expected_size BETWEEN 1 AND 10000000", name="ck_seller_media_expected_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="UPLOAD_PENDING")
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
