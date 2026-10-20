"""Persist passed moderation checklist codes with immutable decisions."""

from alembic import op
import sqlalchemy as sa


revision = "0025_moderation_passed_rules"
down_revision = "0024_structured_audit_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("passed_rules", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError("Passed-rule evidence is immutable and cannot be discarded")
