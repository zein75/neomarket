"""Add immutable versioned Admin policy definitions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_admin_policies"
down_revision = "0009_version_moderation_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("code", "version", name="uq_admin_policy_code_version"),
        sa.CheckConstraint("version >= 1", name="ck_admin_policy_version_positive"),
    )
    op.create_index("ix_admin_policies_code_status", "admin_policies", ["code", "status", "version"])


def downgrade() -> None:
    op.drop_index("ix_admin_policies_code_status", table_name="admin_policies")
    op.drop_table("admin_policies")
