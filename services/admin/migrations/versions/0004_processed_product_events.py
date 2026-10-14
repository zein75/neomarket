"""Persist Admin product-event receipts for idempotent replay."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_processed_product_events"
down_revision = "0003_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_product_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_product_events")
