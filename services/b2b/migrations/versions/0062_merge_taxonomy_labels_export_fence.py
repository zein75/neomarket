"""Merge category label and inventory export migration heads."""


revision = "0062_tax_labels_export_fence"
down_revision = ("0061_category_localized_labels", "0061_export_lease_fence")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
