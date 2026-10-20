"""Add durable owner-scoped checkout attempt status records."""

from alembic import op
import sqlalchemy as sa


revision = "0032_checkout_attempts"
down_revision = "0031_order_delivery_method"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkout_attempts",
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("buyer_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("buyer_id", "idempotency_key", name="uq_checkout_attempts_buyer_key"),
    )
    op.create_index("ix_checkout_attempts_buyer_id", "checkout_attempts", ["buyer_id"])


def downgrade() -> None:
    op.drop_index("ix_checkout_attempts_buyer_id", table_name="checkout_attempts")
    op.drop_table("checkout_attempts")
