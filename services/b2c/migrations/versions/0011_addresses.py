"""add buyer addresses

Revision ID: 0011_addresses
Revises: 0010_order_request_fingerprint
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_addresses"
down_revision: Union[str, None] = "0010_order_request_fingerprint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("region", sa.String(100)),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("street", sa.String(255), nullable=False),
        sa.Column("building", sa.String(50), nullable=False),
        sa.Column("apartment", sa.String(50)),
        sa.Column("postal_code", sa.String(20)),
        sa.Column("recipient_name", sa.String(255)),
        sa.Column("recipient_phone", sa.String(30)),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comment", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("addresses")
