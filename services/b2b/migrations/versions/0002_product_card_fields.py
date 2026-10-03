"""product card fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("category_id", sa.UUID(), nullable=True))
    op.add_column(
        "products",
        sa.Column("images", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "products",
        sa.Column(
            "characteristics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="CREATED",
        ),
    )
    op.alter_column("products", "images", server_default=None)
    op.alter_column("products", "characteristics", server_default=None)
    op.alter_column("products", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "status")
    op.drop_column("products", "characteristics")
    op.drop_column("products", "images")
    op.drop_column("products", "category_id")
