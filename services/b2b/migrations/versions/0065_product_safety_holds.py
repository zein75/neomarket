"""Persist Admin product safety holds."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0065_product_safety_holds"
down_revision: Union[str, None] = "0064_seller_draft_autosaves"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("safety_hold_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("safety_hold_reason_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "safety_hold_reason_code")
    op.drop_column("products", "safety_hold_until")
