"""add order status history

Revision ID: 0013_order_status_history
Revises: 0012_order_cancellation_metadata
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013_order_status_history"
down_revision: Union[str, None] = "0012_order_cancellation_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "CREATED", "PAID", "ASSEMBLING", "DELIVERING", "DELIVERED",
                "CANCELLED", "CANCEL_PENDING", name="orderstatus", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("order_status_history")
