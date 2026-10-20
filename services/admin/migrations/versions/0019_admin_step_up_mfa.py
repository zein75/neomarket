"""Persist recent step-up authentication and OIDC token replay receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_admin_step_up_mfa"
down_revision = "0018_admin_oidc_jti_replay_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_web_sessions", sa.Column("step_up_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_admin_web_session_step_up_expiry",
        "admin_web_sessions",
        "step_up_expires_at IS NULL OR step_up_expires_at <= absolute_expires_at",
    )
    op.create_table(
        "admin_oidc_token_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("jti_hash", name="uq_admin_oidc_token_receipts_jti_hash"),
        sa.CheckConstraint("purpose IN ('SESSION_EXCHANGE', 'STEP_UP')", name="ck_admin_oidc_receipt_purpose"),
    )
    op.create_index("ix_admin_oidc_token_receipts_expiry", "admin_oidc_token_receipts", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_oidc_token_receipts_expiry", table_name="admin_oidc_token_receipts")
    op.drop_table("admin_oidc_token_receipts")
    op.drop_constraint("ck_admin_web_session_step_up_expiry", "admin_web_sessions", type_="check")
    op.drop_column("admin_web_sessions", "step_up_expires_at")
