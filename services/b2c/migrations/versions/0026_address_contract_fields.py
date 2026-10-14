"""Store the canonical public address representation."""

from alembic import op
import sqlalchemy as sa


revision = "0026_address_contract_fields"
down_revision = "0025_delivery_finalizing_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column("label", sa.String(length=100), nullable=True))
    op.add_column("addresses", sa.Column("address_line", sa.String(length=500), nullable=True))
    op.execute("UPDATE addresses SET label = COALESCE(city, 'Address') WHERE label IS NULL")
    op.execute("UPDATE addresses SET address_line = COALESCE(street, '') WHERE address_line IS NULL")


def downgrade() -> None:
    op.drop_column("addresses", "address_line")
    op.drop_column("addresses", "label")
