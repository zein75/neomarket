"""Persist resumable large taxonomy impact previews."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0060_taxonomy_impact_jobs"
down_revision = "0059_seller_inventory_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_impact_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_version", sa.Integer(), nullable=False),
        sa.Column("category_version", sa.Integer(), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="QUEUED"),
        sa.Column("stage", sa.String(length=16), nullable=False, server_default="CATEGORIES"),
        sa.Column("category_cursor", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_cursor", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("total_categories", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_categories", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_product_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_sellers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_reapproval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')", name="ck_taxonomy_impact_jobs_status"),
        sa.CheckConstraint("stage IN ('CATEGORIES', 'PRODUCTS', 'FINALIZE')", name="ck_taxonomy_impact_jobs_stage"),
        sa.CheckConstraint("processed_categories >= 0 AND processed_products >= 0", name="ck_taxonomy_impact_jobs_progress"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taxonomy_impact_jobs_worker",
        "taxonomy_impact_jobs",
        ["status", "created_at"],
    )
    op.create_table(
        "taxonomy_impact_redirects",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_path", sa.String(length=4096), nullable=False),
        sa.Column("new_path", sa.String(length=4096), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["taxonomy_impact_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "category_id"),
    )
    op.create_index("ix_taxonomy_impact_redirects_job", "taxonomy_impact_redirects", ["job_id", "category_id"])


def downgrade() -> None:
    op.drop_index("ix_taxonomy_impact_redirects_job", table_name="taxonomy_impact_redirects")
    op.drop_table("taxonomy_impact_redirects")
    op.drop_index("ix_taxonomy_impact_jobs_worker", table_name="taxonomy_impact_jobs")
    op.drop_table("taxonomy_impact_jobs")
