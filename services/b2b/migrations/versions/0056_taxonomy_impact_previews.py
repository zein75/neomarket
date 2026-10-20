"""Persist short-lived, version-bound taxonomy impact previews."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0056_taxonomy_impact_previews"
down_revision = "0055_attribute_definitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_impact_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("impact_hash", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_version", sa.Integer(), nullable=False),
        sa.Column("category_version", sa.Integer(), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_by_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_taxonomy_impact_previews_hash", "taxonomy_impact_previews", ["impact_hash"], unique=True)
    op.create_index("ix_taxonomy_impact_previews_expiry", "taxonomy_impact_previews", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_taxonomy_impact_previews_expiry", table_name="taxonomy_impact_previews")
    op.drop_index("ix_taxonomy_impact_previews_hash", table_name="taxonomy_impact_previews")
    op.drop_table("taxonomy_impact_previews")
