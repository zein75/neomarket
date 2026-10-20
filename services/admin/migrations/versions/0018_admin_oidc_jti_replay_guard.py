"""Require one-time exchange of each verified OIDC token ID."""

from alembic import op
import sqlalchemy as sa


revision = "0018_admin_oidc_jti_replay_guard"
down_revision = "0017_admin_web_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_web_sessions", sa.Column("oidc_jti_hash", sa.String(length=64), nullable=True))
    op.add_column("admin_web_sessions", sa.Column("oidc_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_admin_web_sessions_oidc_jti_hash", "admin_web_sessions", ["oidc_jti_hash"])
    op.create_check_constraint(
        "ck_admin_web_session_jti_expiry",
        "admin_web_sessions",
        "oidc_jti_hash IS NULL OR oidc_token_expires_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_admin_web_session_jti_expiry", "admin_web_sessions", type_="check")
    op.drop_constraint("uq_admin_web_sessions_oidc_jti_hash", "admin_web_sessions", type_="unique")
    op.drop_column("admin_web_sessions", "oidc_token_expires_at")
    op.drop_column("admin_web_sessions", "oidc_jti_hash")
