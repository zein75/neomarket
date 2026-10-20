"""Add the authoritative B2B product attribute registry."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0055_attribute_definitions"
down_revision = "0054_taxonomy_command_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attribute_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("data_type", sa.String(length=16), nullable=False),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("filterable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("searchable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("comparable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("variant_dimension", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("pii", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("data_type IN ('string','integer','decimal','boolean','enum','multi_enum','date','reference')", name="ck_attribute_definitions_data_type"),
        sa.CheckConstraint("version >= 1", name="ck_attribute_definitions_version_positive"),
        sa.CheckConstraint("status IN ('ACTIVE','HIDDEN','ARCHIVED')", name="ck_attribute_definitions_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_attribute_definitions_code_ci", "attribute_definitions", [sa.text("lower(code)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_attribute_definitions_code_ci", table_name="attribute_definitions")
    op.drop_table("attribute_definitions")
