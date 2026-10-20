"""Persist signed carrier lifecycle events and apply them in order."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0050_carrier_webhooks"
down_revision = "0049_carrier_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_seller_shipments_status", "seller_shipments", type_="check")
    op.create_check_constraint(
        "ck_seller_shipments_status",
        "seller_shipments",
        "status IN ('PACKED', 'DISPATCHED', 'DELIVERED')",
    )
    op.add_column(
        "seller_shipments",
        sa.Column("status_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "carrier_webhook_receipts",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("aggregate_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("shipment_id", "aggregate_revision", name="uq_carrier_webhook_shipment_revision"),
    )
    op.create_index("ix_carrier_webhook_receipts_shipment_id", "carrier_webhook_receipts", ["shipment_id"])


def downgrade() -> None:
    op.drop_index("ix_carrier_webhook_receipts_shipment_id", table_name="carrier_webhook_receipts")
    op.drop_table("carrier_webhook_receipts")
    op.drop_column("seller_shipments", "status_revision")
    op.drop_constraint("ck_seller_shipments_status", "seller_shipments", type_="check")
    op.create_check_constraint("ck_seller_shipments_status", "seller_shipments", "status = 'PACKED'")
