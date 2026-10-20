"""Add versioned staff permissions and maker-checker operations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_admin_iam_operations"
down_revision = "0007_revision_bound_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "staff_principals",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_table(
        "admin_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="WAITING_APPROVAL", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approval_key", sa.String(length=128), nullable=True),
        sa.Column("approval_hash", sa.String(length=64), nullable=True),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_key", sa.String(length=128), nullable=True),
        sa.Column("cancel_hash", sa.String(length=64), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_admin_operation_actor_key"),
        sa.UniqueConstraint("approval_key", name="uq_admin_operation_approval_key"),
        sa.UniqueConstraint("cancel_key", name="uq_admin_operation_cancel_key"),
    )
    op.create_index(
        "ix_admin_operations_status_created",
        "admin_operations",
        ["status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_operations_status_created", table_name="admin_operations")
    op.drop_table("admin_operations")
    op.drop_column("staff_principals", "version")
