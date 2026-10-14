"""Add worker leases to moderation decision outbox."""

from alembic import op
import sqlalchemy as sa


revision = "0006_moderation_outbox_leases"
down_revision = "0005_moderation_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("moderation_outbox_events", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    op.add_column("moderation_outbox_events", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_moderation_outbox_lease",
        "moderation_outbox_events",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_outbox_lease", table_name="moderation_outbox_events")
    op.drop_column("moderation_outbox_events", "lease_until")
    op.drop_column("moderation_outbox_events", "lease_owner")
