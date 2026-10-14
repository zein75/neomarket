"""Persist backoff schedule for delivery fulfillment retries."""

from alembic import op
import sqlalchemy as sa


revision = "0024_fulfillment_retry_schedule"
down_revision = "0023_checkout_intent_buyer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_fulfillments",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pending_fulfillments_next_retry_at",
        "pending_fulfillments",
        ["next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_fulfillments_next_retry_at",
        table_name="pending_fulfillments",
    )
    op.drop_column("pending_fulfillments", "next_retry_at")
