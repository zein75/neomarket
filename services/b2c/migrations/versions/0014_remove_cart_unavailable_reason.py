"""remove persisted cart availability reason

Revision ID: 0014_remove_cart_unavailable_reason
Revises: 0013_order_status_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_remove_cart_unavailable_reason"
down_revision: Union[str, None] = "0013_order_status_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("cart_items", "unavailable_reason")


def downgrade() -> None:
    op.add_column(
        "cart_items",
        sa.Column("unavailable_reason", sa.String(length=50), nullable=True),
    )
