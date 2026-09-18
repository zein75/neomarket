"""store order cancellation metadata

Revision ID: 0012_order_cancellation_metadata
Revises: 0011_addresses
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_order_cancellation_metadata"
down_revision: Union[str, None] = "0011_addresses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cancel_reason", sa.String(length=500), nullable=True))
    op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "cancelled_at")
    op.drop_column("orders", "cancel_reason")
