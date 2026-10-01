"""persist unavailable cart state received from B2B events

Revision ID: 0015_cart_event_availability
Revises: 0014_remove_cart_unavailable_reason
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_cart_event_availability"
down_revision: Union[str, None] = "0014_remove_cart_unavailable_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cart_items",
        sa.Column("unavailable_reason", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cart_items", "unavailable_reason")
