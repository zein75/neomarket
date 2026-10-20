"""Add versioned Admin taxonomy metadata to the B2B source of truth."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0053_admin_taxonomy_snapshot"
down_revision = "0052_moderation_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("code", sa.String(length=80), nullable=True))
    op.add_column("categories", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "categories",
        sa.Column("status", sa.String(length=24), server_default="ACTIVE", nullable=False),
    )
    op.add_column("categories", sa.Column("sort_order", sa.Integer(), nullable=True))
    op.add_column("categories", sa.Column("seo_title", sa.String(length=255), nullable=True))
    op.add_column(
        "categories",
        sa.Column("image_media_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "categories",
        sa.Column("schema_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "categories",
        sa.Column(
            "attribute_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE categories SET code = CASE WHEN length(slug) <= 80 THEN slug "
        "ELSE left(slug, 63) || '_' || left(replace(id::text, '-', ''), 16) END, "
        "status = CASE WHEN is_active THEN 'ACTIVE' ELSE 'HIDDEN' END"
    )
    op.alter_column("categories", "code", nullable=False)
    op.create_unique_constraint("uq_categories_code", "categories", ["code"])
    op.create_table(
        "taxonomy_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_taxonomy_state_singleton"),
        sa.CheckConstraint("version >= 1", name="ck_taxonomy_state_version_positive"),
    )
    op.execute("INSERT INTO taxonomy_state (id, version) VALUES (1, 1)")


def downgrade() -> None:
    op.drop_table("taxonomy_state")
    op.drop_constraint("uq_categories_code", "categories", type_="unique")
    op.drop_column("categories", "attribute_rules")
    op.drop_column("categories", "schema_version")
    op.drop_column("categories", "image_media_id")
    op.drop_column("categories", "seo_title")
    op.drop_column("categories", "sort_order")
    op.drop_column("categories", "status")
    op.drop_column("categories", "description")
    op.drop_column("categories", "code")
