"""Keep compensated ambiguous checkout operations as durable tombstones.

Revision ID: 0021_checkout_compensation_tombstone
Revises: 0020_checkout_reserve_intent
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_checkout_compensation_tombstone"
down_revision = "0020_checkout_reserve_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_reservation_compensations",
        sa.Column("compensated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_reservation_compensations", "compensated_at")
