"""Keep an immutable payload fingerprint for B2B inbox idempotency."""

from alembic import op
import sqlalchemy as sa


revision = "0029_processed_event_payload_hash"
down_revision = "0028_refresh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processed_b2b_events",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processed_b2b_events", "payload_hash")
