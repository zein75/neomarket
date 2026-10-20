"""Add privacy-preserving complaint cases and immutable actions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_admin_complaints"
down_revision = "0010_admin_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_complaints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reporter_ref", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("entity_type IN ('PRODUCT','SELLER','MEDIA')", name="ck_admin_complaint_entity_type"),
        sa.CheckConstraint("status IN ('NEW','TRIAGED','IN_REVIEW','CLOSED','ESCALATED')", name="ck_admin_complaint_status"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_admin_complaint_priority"),
        sa.CheckConstraint("version >= 1", name="ck_admin_complaint_version"),
        sa.ForeignKeyConstraint(["assigned_to"], ["staff_principals.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_admin_complaints_status_priority_created", "admin_complaints", ["status", "priority", "created_at", "id"])
    op.create_table(
        "admin_complaint_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("complaint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["admin_complaints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_admin_complaint_actor_key"),
    )
    op.create_index("ix_admin_complaint_actions_complaint_created", "admin_complaint_actions", ["complaint_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_complaint_actions_complaint_created", table_name="admin_complaint_actions")
    op.drop_table("admin_complaint_actions")
    op.drop_index("ix_admin_complaints_status_priority_created", table_name="admin_complaints")
    op.drop_table("admin_complaints")
