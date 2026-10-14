"""add durable inventory lifecycle, reservation lines and ledger"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0019_inventory_lifecycle_ledger"
down_revision: Union[str, None] = "0018_sku_inventory_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "inventory_order_lifecycle",
        sa.Column("order_id", uuid, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="NEW"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(64)),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('NEW', 'RESERVED', 'CANCELLED', 'FULFILLED')", name="ck_inventory_lifecycle_state"),
        sa.CheckConstraint("version >= 0", name="ck_inventory_lifecycle_version"),
    )
    op.create_table(
        "reservation_lines",
        sa.Column("order_id", uuid, nullable=False),
        sa.Column("sku_id", uuid, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["order_id"], ["inventory_order_lifecycle.order_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("order_id", "sku_id"),
        sa.CheckConstraint("quantity > 0", name="ck_reservation_lines_quantity"),
        sa.CheckConstraint("state IN ('ACTIVE', 'RELEASED', 'FULFILLED')", name="ck_reservation_lines_state"),
    )
    op.create_table(
        "inventory_ledger",
        sa.Column("entry_id", uuid, primary_key=True),
        sa.Column("event_id", uuid, nullable=False, unique=True),
        sa.Column("order_id", uuid),
        sa.Column("sku_id", uuid, nullable=False),
        sa.Column("delta_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delta_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(128)),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("inventory_ledger")
    op.drop_table("reservation_lines")
    op.drop_table("inventory_order_lifecycle")
