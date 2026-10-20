"""Persist the operational SLA deadline for newly received complaints."""

from alembic import op
import sqlalchemy as sa


revision = "0026_admin_complaint_deadline"
down_revision = "0025_moderation_passed_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_complaints", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_admin_complaints_status_deadline", "admin_complaints", ["status", "deadline_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_complaints_status_deadline", table_name="admin_complaints")
    op.drop_column("admin_complaints", "deadline_at")
