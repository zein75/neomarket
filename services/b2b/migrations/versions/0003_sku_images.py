"""sku images

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE products SET status = 'ON_MODERATION' WHERE status = 'MODERATION'")
    op.execute("UPDATE products SET status = 'MODERATED' WHERE status = 'ACTIVE'")
    op.execute("UPDATE products SET status = 'BLOCKED' WHERE status = 'REJECTED'")
    op.add_column(
        "skus",
        sa.Column("images", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "skus",
        sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("skus", "images", server_default=None)
    op.alter_column("skus", "reserved_quantity", server_default=None)


def downgrade() -> None:
    op.drop_column("skus", "reserved_quantity")
    op.drop_column("skus", "images")
    op.execute("UPDATE products SET status = 'MODERATION' WHERE status = 'ON_MODERATION'")
    op.execute("UPDATE products SET status = 'ACTIVE' WHERE status = 'MODERATED'")
    op.execute("UPDATE products SET status = 'REJECTED' WHERE status = 'BLOCKED'")
