"""Persist the request identity of a pre-reserve checkout intent.

Revision ID: 0020_checkout_reserve_intent
Revises: 0019_reserve_compensation
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_checkout_reserve_intent"
down_revision = "0019_reserve_compensation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_reservation_compensations",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_reservation_compensations", "request_fingerprint")
