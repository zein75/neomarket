"""Queue media only after explicit completion and enforce seller ownership FK."""

from alembic import op


revision = "0046_media_complete_queue"
down_revision = "0045_seller_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_seller_media_state", "seller_media_assets", type_="check")
    op.create_check_constraint(
        "ck_seller_media_state",
        "seller_media_assets",
        "state IN ('UPLOAD_PENDING', 'UPLOADED', 'SCAN_QUEUED', 'SCANNING', 'READY', 'REJECTED', 'EXPIRED')",
    )
    op.create_foreign_key(
        "fk_seller_media_assets_seller_id_sellers",
        "seller_media_assets",
        "sellers",
        ["seller_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_seller_media_assets_seller_id_sellers", "seller_media_assets", type_="foreignkey")
    op.drop_constraint("ck_seller_media_state", "seller_media_assets", type_="check")
    op.create_check_constraint(
        "ck_seller_media_state",
        "seller_media_assets",
        "state IN ('UPLOAD_PENDING', 'UPLOADED', 'SCANNING', 'READY', 'REJECTED', 'EXPIRED')",
    )
