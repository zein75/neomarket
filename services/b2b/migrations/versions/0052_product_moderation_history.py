"""Persist seller-visible moderation decision history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0052_moderation_history"
down_revision = "0051_member_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_moderation_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_revision", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.String(length=4000), nullable=True),
        sa.Column("field_reports", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_product_moderation_history_event"),
    )
    op.create_index("ix_product_moderation_history_seller_id", "product_moderation_history", ["seller_id"])
    op.create_index("ix_product_moderation_history_product_time", "product_moderation_history", ["product_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_product_moderation_history_product_time", table_name="product_moderation_history")
    op.drop_index("ix_product_moderation_history_seller_id", table_name="product_moderation_history")
    op.drop_table("product_moderation_history")
