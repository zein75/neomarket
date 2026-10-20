"""Persist seller packing manifests and bounded shipment quantities."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0048_order_shipments"
down_revision = "0047_order_receipt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("seller_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PACKED"),
        sa.Column("packed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("seller_order_id", "idempotency_key", name="uq_seller_shipments_order_key"),
        sa.CheckConstraint("status = 'PACKED'", name="ck_seller_shipments_status"),
    )
    op.create_index("ix_seller_shipments_seller_order_id", "seller_shipments", ["seller_order_id"])
    op.create_index("ix_seller_shipments_seller_id", "seller_shipments", ["seller_id"])
    op.create_table(
        "seller_shipment_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seller_order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seller_order_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.UniqueConstraint("shipment_id", "seller_order_item_id", name="uq_seller_shipment_line_item"),
        sa.CheckConstraint("quantity > 0", name="ck_seller_shipment_lines_quantity_positive"),
    )
    op.create_index("ix_seller_shipment_lines_shipment_id", "seller_shipment_lines", ["shipment_id"])
    op.create_index("ix_seller_shipment_lines_seller_order_item_id", "seller_shipment_lines", ["seller_order_item_id"])


def downgrade() -> None:
    op.drop_index("ix_seller_shipment_lines_seller_order_item_id", table_name="seller_shipment_lines")
    op.drop_index("ix_seller_shipment_lines_shipment_id", table_name="seller_shipment_lines")
    op.drop_table("seller_shipment_lines")
    op.drop_index("ix_seller_shipments_seller_id", table_name="seller_shipments")
    op.drop_index("ix_seller_shipments_seller_order_id", table_name="seller_shipments")
    op.drop_table("seller_shipments")
