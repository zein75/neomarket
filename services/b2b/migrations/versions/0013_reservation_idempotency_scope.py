"""scope reservation idempotency by sku

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reservation_operations",
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.drop_index("ix_reservations_idempotency_key", table_name="reservations")
    op.create_index(
        "ix_reservations_idempotency_key_sku_id",
        "reservations",
        ["idempotency_key", "sku_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reservations_idempotency_key_sku_id",
        table_name="reservations",
    )
    op.create_index(
        "ix_reservations_idempotency_key",
        "reservations",
        ["idempotency_key"],
        unique=True,
    )
    op.drop_table("reservation_operations")
