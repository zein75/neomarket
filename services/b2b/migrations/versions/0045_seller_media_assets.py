"""Persist seller media upload intents and scan state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0045_seller_media_assets"
down_revision = "0044_inventory_import_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "seller_media_assets",
        sa.Column("id", uuid, nullable=False),
        sa.Column("seller_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("expected_content_type", sa.String(64), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), server_default="UPLOAD_PENDING", nullable=False),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("content_type", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("public_url", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state IN ('UPLOAD_PENDING', 'UPLOADED', 'SCANNING', 'READY', 'REJECTED', 'EXPIRED')",
            name="ck_seller_media_state",
        ),
        sa.CheckConstraint("expected_size BETWEEN 1 AND 10000000", name="ck_seller_media_expected_size"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "idempotency_key", name="uq_seller_media_idempotency"),
    )
    op.create_index("ix_seller_media_assets_seller_id", "seller_media_assets", ["seller_id"])
    op.create_index("ix_seller_media_assets_scan_queue", "seller_media_assets", ["state", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_seller_media_assets_scan_queue", table_name="seller_media_assets")
    op.drop_index("ix_seller_media_assets_seller_id", table_name="seller_media_assets")
    op.drop_table("seller_media_assets")
