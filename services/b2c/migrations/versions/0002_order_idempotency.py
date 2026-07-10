"""order idempotency

Revision ID: 0002_order_idempotency
Revises: cbdd3d7563bf
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_order_idempotency"
down_revision: Union[str, None] = "cbdd3d7563bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.execute(
        "UPDATE orders SET idempotency_key = 'legacy-' || id::text "
        "WHERE idempotency_key IS NULL"
    )
    op.alter_column("orders", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_orders_idempotency_key",
        "orders",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "idempotency_key")
