"""Add independent, immutable appeal review records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_admin_appeals"
down_revision = "0011_admin_complaints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_appeals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("original_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claimant_ref", sa.String(64), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reviewer_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('SUBMITTED','TRIAGED','IN_REVIEW','UPHELD','OVERTURNED','PARTIALLY_UPHELD','CLOSED')", name="ck_admin_appeal_status"),
        sa.CheckConstraint("version >= 1", name="ck_admin_appeal_version"),
        sa.ForeignKeyConstraint(["original_decision_id"], ["moderation_decision_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_staff_id"], ["staff_principals.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_admin_appeals_status_created", "admin_appeals", ["status", "created_at", "id"])
    op.create_table(
        "admin_appeal_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("appeal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("outcome IN ('UPHELD','OVERTURNED','PARTIALLY_UPHELD')", name="ck_admin_appeal_outcome"),
        sa.ForeignKeyConstraint(["appeal_id"], ["admin_appeals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_staff_id"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reviewer_staff_id", "idempotency_key", name="uq_admin_appeal_reviewer_key"),
        sa.UniqueConstraint("appeal_id", name="uq_admin_appeal_single_decision"),
    )


def downgrade() -> None:
    op.drop_table("admin_appeal_decisions")
    op.drop_index("ix_admin_appeals_status_created", table_name="admin_appeals")
    op.drop_table("admin_appeals")
