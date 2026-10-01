"""store durable cancellation retry scheduling data

Revision ID: 0017_order_cancellation_retry_schedule
Revises: 0016_cart_identity_constraints_and_dynamic_availability
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_order_cancellation_retry_schedule"
down_revision: Union[str, None] = "0016_cart_identity_constraints_and_dynamic_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("cancel_retry_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column("cancel_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("orders", "cancel_retry_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("orders", "cancel_retry_at")
    op.drop_column("orders", "cancel_retry_attempts")
