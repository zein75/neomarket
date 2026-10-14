"""Add the durable delivery finalization state from the order contract."""

from alembic import op


revision = "0025_delivery_finalizing_status"
down_revision = "0024_fulfillment_retry_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'DELIVERY_FINALIZING'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place. Existing rows
    # are not rewritten; a forward-only migration is required for this state.
    pass
