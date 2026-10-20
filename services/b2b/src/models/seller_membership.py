import uuid
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SellerRole(StrEnum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    CATALOG_EDITOR = "CATALOG_EDITOR"
    WAREHOUSE_OPERATOR = "WAREHOUSE_OPERATOR"
    SUPPORT = "SUPPORT"
    FINANCE = "FINANCE"
    VIEWER = "VIEWER"


class SellerMembership(Base, TimestampMixin):
    __tablename__ = "seller_memberships"
    __table_args__ = (
        UniqueConstraint("seller_id", "user_id", name="uq_seller_memberships_seller_user"),
        CheckConstraint(
            "role IN ('OWNER', 'MANAGER', 'CATALOG_EDITOR', 'WAREHOUSE_OPERATOR', 'SUPPORT', 'FINANCE', 'VIEWER')",
            name="ck_seller_memberships_role",
        ),
        Index("ix_seller_memberships_user_active", "user_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
