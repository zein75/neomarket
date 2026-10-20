"""Persist retryable carrier label operations and local simulator receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0049_carrier_ops"
down_revision = "0048_order_shipments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_carrier_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=24), server_default="LOCAL_TEST", nullable=False),
        sa.Column("provider_operation_ref", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING_PROVIDER", nullable=False),
        sa.Column("tracking_number", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("shipment_id", name="uq_seller_carrier_operation_shipment"),
        sa.UniqueConstraint("idempotency_key", name="uq_seller_carrier_operation_key"),
        sa.UniqueConstraint("provider_operation_ref", name="uq_seller_carrier_operation_ref"),
        sa.UniqueConstraint("tracking_number", name="uq_seller_carrier_operations_tracking_number"),
        sa.CheckConstraint("provider = 'LOCAL_TEST'", name="ck_seller_carrier_operations_provider"),
        sa.CheckConstraint("status IN ('PENDING_PROVIDER', 'LABEL_CREATED')", name="ck_seller_carrier_operations_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_seller_carrier_operations_attempts_nonnegative"),
    )
    op.create_index("ix_seller_carrier_operations_seller_id", "seller_carrier_operations", ["seller_id"])
    op.create_table(
        "local_carrier_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_ref", sa.String(length=160), nullable=False),
        sa.Column("tracking_number", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("shipment_id", name="uq_local_carrier_label_shipment"),
        sa.UniqueConstraint("operation_ref", name="uq_local_carrier_label_operation_ref"),
        sa.UniqueConstraint("tracking_number", name="uq_local_carrier_labels_tracking_number"),
    )


def downgrade() -> None:
    op.drop_table("local_carrier_labels")
    op.drop_index("ix_seller_carrier_operations_seller_id", table_name="seller_carrier_operations")
    op.drop_table("seller_carrier_operations")
