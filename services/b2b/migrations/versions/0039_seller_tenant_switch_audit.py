"""Record explicit seller organization context switches."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0039_seller_tenant_switch_audit"
down_revision = "0038_seller_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_tenant_switch_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_role", sa.String(length=32), nullable=False),
        sa.Column("target_role", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seller_tenant_switch_audit_user_id",
        "seller_tenant_switch_audit",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_seller_tenant_switch_audit_user_id", table_name="seller_tenant_switch_audit")
    op.drop_table("seller_tenant_switch_audit")
