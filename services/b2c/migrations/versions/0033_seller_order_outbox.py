"""Persist seller ownership snapshots and transactional allocation events."""

from alembic import op
import sqlalchemy as sa


revision = "0033_seller_order_outbox"
down_revision = "0032_checkout_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_items", sa.Column("seller_id", sa.UUID(), nullable=True))
    op.create_table(
        "seller_order_outbox",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("seller_order_id", sa.UUID(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("seller_order_id", name="uq_seller_order_outbox_seller_order"),
    )
    op.create_index("ix_seller_order_outbox_status", "seller_order_outbox", ["status", "next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_seller_order_outbox_status", table_name="seller_order_outbox")
    op.drop_table("seller_order_outbox")
    op.drop_column("order_items", "seller_id")
