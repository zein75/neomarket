"""Add authoritative brands, aliases, merge receipts, and product references."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0057_brand_registry"
down_revision = "0056_taxonomy_impact_previews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("evidence_ref", sa.String(length=2048), nullable=True),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','VERIFIED','RESTRICTED','MERGED')", name="ck_brands_status"),
        sa.CheckConstraint("version >= 1", name="ck_brands_version_positive"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_brands_normalized_name", "brands", ["normalized_name"], unique=True)
    op.create_table(
        "brand_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_aliases_brand_id", "brand_aliases", ["brand_id"])
    op.create_index("uq_brand_aliases_normalized", "brand_aliases", ["normalized_alias"], unique=True)
    op.create_table(
        "brand_merge_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("taxonomy_version", sa.Integer(), nullable=False),
        sa.Column("product_count", sa.Integer(), nullable=False),
        sa.Column("impact_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_by_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["source_brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_merge_previews_hash", "brand_merge_previews", ["impact_hash"], unique=True)
    op.create_table(
        "brand_merge_history",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("product_references_moved", sa.Integer(), nullable=False),
        sa.Column("impact_hash", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("approved_by_staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.add_column("products", sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_products_brand_id_brands", "products", "brands", ["brand_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_products_brand_id", "products", ["brand_id"])


def downgrade() -> None:
    op.drop_index("ix_products_brand_id", table_name="products")
    op.drop_constraint("fk_products_brand_id_brands", "products", type_="foreignkey")
    op.drop_column("products", "brand_id")
    op.drop_table("brand_merge_history")
    op.drop_index("ix_brand_merge_previews_hash", table_name="brand_merge_previews")
    op.drop_table("brand_merge_previews")
    op.drop_index("uq_brand_aliases_normalized", table_name="brand_aliases")
    op.drop_index("ix_brand_aliases_brand_id", table_name="brand_aliases")
    op.drop_table("brand_aliases")
    op.drop_index("uq_brands_normalized_name", table_name="brands")
    op.drop_table("brands")
