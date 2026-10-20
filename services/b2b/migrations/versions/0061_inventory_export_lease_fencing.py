"""Fence stale inventory export workers from publishing artifacts."""

from alembic import op
import sqlalchemy as sa


revision = "0061_export_lease_fence"
down_revision = "0060_taxonomy_impact_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seller_inventory_exports",
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("seller_inventory_exports", "lease_generation")
