"""order checkout contract fields

Revision ID: 0003_order_checkout_contract
Revises: 0002_order_idempotency
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_order_checkout_contract"
down_revision: Union[str, None] = "0002_order_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("address_id", sa.UUID(), nullable=True))
    op.add_column("orders", sa.Column("payment_method_id", sa.UUID(), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "address",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.alter_column("orders", "address", server_default=None)


def downgrade() -> None:
    op.drop_column("orders", "address")
    op.drop_column("orders", "payment_method_id")
    op.drop_column("orders", "address_id")
