"""Persist moderation decisions before delivery to B2B."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_moderation_outbox"
down_revision = "0004_processed_product_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_moderation_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_moderation_outbox_pending",
        "moderation_outbox_events",
        ["status", "next_retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_outbox_pending", table_name="moderation_outbox_events")
    op.drop_table("moderation_outbox_events")
