"""Bind durable checkout intents to their buyer for safe polling."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_checkout_intent_buyer"
down_revision = "0022_compensation_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_reservation_compensations",
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_pending_reservation_compensations_buyer_id",
        "pending_reservation_compensations",
        ["buyer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_reservation_compensations_buyer_id",
        table_name="pending_reservation_compensations",
    )
    op.drop_column("pending_reservation_compensations", "buyer_id")
