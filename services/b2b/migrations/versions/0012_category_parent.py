"""category parent

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("parent_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_categories_parent_id_categories",
        "categories",
        "categories",
        ["parent_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_categories_parent_id_categories",
        "categories",
        type_="foreignkey",
    )
    op.drop_column("categories", "parent_id")
