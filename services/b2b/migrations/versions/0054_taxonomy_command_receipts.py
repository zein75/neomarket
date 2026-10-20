"""Persist idempotent receipts for Admin taxonomy commands."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0054_taxonomy_command_receipts"
down_revision = "0053_admin_taxonomy_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_command_receipts",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('APPLIED', 'CONFLICT', 'REJECTED')", name="ck_taxonomy_command_receipt_status"),
    )


def downgrade() -> None:
    op.drop_table("taxonomy_command_receipts")
