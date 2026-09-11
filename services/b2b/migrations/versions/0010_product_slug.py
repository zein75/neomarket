"""product slug

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("slug", sa.String(length=320), nullable=True))
    op.create_index(op.f("ix_products_slug"), "products", ["slug"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_products_slug"), table_name="products")
    op.drop_column("products", "slug")
