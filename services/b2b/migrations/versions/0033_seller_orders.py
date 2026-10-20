"""Add seller-scoped order allocation projections."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0033_seller_orders"
down_revision = "0032_sku_rev"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "seller_orders",
        sa.Column("id", uuid, nullable=False),
        sa.Column("buyer_order_id", uuid, nullable=False),
        sa.Column("seller_id", uuid, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="CREATED", nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_minor >= 0", name="ck_seller_orders_total_nonnegative"),
        sa.CheckConstraint("revision >= 1", name="ck_seller_orders_revision_positive"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "buyer_order_id", name="uq_seller_orders_tenant_buyer_order"),
    )
    op.create_index("ix_seller_orders_buyer_order_id", "seller_orders", ["buyer_order_id"])
    op.create_index("ix_seller_orders_seller_id", "seller_orders", ["seller_id"])
    op.create_table(
        "seller_order_items",
        sa.Column("id", uuid, nullable=False),
        sa.Column("seller_order_id", uuid, nullable=False),
        sa.Column("sku_id", uuid, nullable=False),
        sa.Column("product_id", uuid, nullable=False),
        sa.Column("product_title", sa.String(length=255), nullable=False),
        sa.Column("sku_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_seller_order_items_quantity_positive"),
        sa.CheckConstraint("unit_price_minor >= 0", name="ck_seller_order_items_price_nonnegative"),
        sa.CheckConstraint("line_total_minor >= 0", name="ck_seller_order_items_total_nonnegative"),
        sa.ForeignKeyConstraint(["seller_order_id"], ["seller_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seller_order_items_seller_order_id", "seller_order_items", ["seller_order_id"])


def downgrade() -> None:
    op.drop_index("ix_seller_order_items_seller_order_id", table_name="seller_order_items")
    op.drop_table("seller_order_items")
    op.drop_index("ix_seller_orders_seller_id", table_name="seller_orders")
    op.drop_index("ix_seller_orders_buyer_order_id", table_name="seller_orders")
    op.drop_table("seller_orders")
