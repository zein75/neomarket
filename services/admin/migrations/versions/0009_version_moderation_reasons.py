"""Add versioned severity and lifecycle fields to moderation reasons."""

from alembic import op
import sqlalchemy as sa


revision = "0009_version_moderation_reasons"
down_revision = "0008_admin_iam_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blocking_reasons", sa.Column("severity", sa.String(length=24), nullable=True))
    op.add_column("blocking_reasons", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.execute(sa.text(
        "UPDATE blocking_reasons SET severity = CASE WHEN hard_block THEN 'HARD_BLOCK' ELSE 'REJECT' END WHERE severity IS NULL"
    ))
    op.alter_column("blocking_reasons", "severity", nullable=False, server_default="REJECT")
    op.create_check_constraint(
        "ck_blocking_reason_severity",
        "blocking_reasons",
        "severity IN ('INFO', 'FIX_REQUIRED', 'REJECT', 'HARD_BLOCK')",
    )
    op.create_check_constraint("ck_blocking_reason_version_positive", "blocking_reasons", "version >= 1")


def downgrade() -> None:
    op.drop_constraint("ck_blocking_reason_version_positive", "blocking_reasons", type_="check")
    op.drop_constraint("ck_blocking_reason_severity", "blocking_reasons", type_="check")
    op.drop_column("blocking_reasons", "version")
    op.drop_column("blocking_reasons", "severity")
