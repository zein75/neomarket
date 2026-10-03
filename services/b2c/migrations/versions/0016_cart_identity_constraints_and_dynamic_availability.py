"""make cart ownership unique and remove stale availability state

Revision ID: 0016_cart_identity
Revises: 0015_cart_event_availability
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_cart_identity"
down_revision: Union[str, None] = "0015_cart_event_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("cart_items", "unavailable_reason")
    op.create_unique_constraint("uq_carts_user_id", "carts", ["user_id"])
    op.create_unique_constraint("uq_carts_session_id", "carts", ["session_id"])


def downgrade() -> None:
    op.drop_constraint("uq_carts_session_id", "carts", type_="unique")
    op.drop_constraint("uq_carts_user_id", "carts", type_="unique")
    op.add_column(
        "cart_items",
        sa.Column("unavailable_reason", sa.String(length=50), nullable=True),
    )
