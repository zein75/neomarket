"""Add seller email verification and onboarding status."""

from alembic import op
import sqlalchemy as sa


revision = "0037_seller_email_verify"
down_revision = "0036_seller_email_ci"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sellers",
        sa.Column("account_status", sa.String(length=32), server_default="ACTIVE", nullable=False),
    )
    op.add_column("sellers", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE sellers SET account_status = CASE WHEN is_active THEN 'ACTIVE' ELSE 'SUSPENDED' END, "
        "email_verified_at = created_at"
    )
    op.create_table(
        "seller_email_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_seller_email_verifications_seller_id",
        "seller_email_verifications",
        ["seller_id"],
    )
    op.create_index(
        "ix_seller_email_verifications_expires_at",
        "seller_email_verifications",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seller_email_verifications_expires_at", table_name="seller_email_verifications")
    op.drop_index("ix_seller_email_verifications_seller_id", table_name="seller_email_verifications")
    op.drop_table("seller_email_verifications")
    op.drop_column("sellers", "email_verified_at")
    op.drop_column("sellers", "account_status")
