"""Persist additive checkout contact, legal consent and quote references."""

from alembic import op
import sqlalchemy as sa

revision = "0030_checkout_fields"
down_revision = "0029_event_payload_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("contact", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("legal_consents", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("quote_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "quote_id")
    op.drop_column("orders", "legal_consents")
    op.drop_column("orders", "contact")
