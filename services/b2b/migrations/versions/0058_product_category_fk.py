"""Block category FK migration on orphan product references."""

from alembic import op
from alembic import context
import sqlalchemy as sa

revision = "0058_product_category_fk"
down_revision = "0057_brand_registry"
branch_labels = None
depends_on = None


def _orphaned_product_category_references(connection) -> list[tuple]:
    return connection.execute(
        sa.text(
            """
            SELECT p.id, p.category_id
            FROM products AS p
            LEFT JOIN categories AS c ON c.id = p.category_id
            WHERE p.category_id IS NOT NULL AND c.id IS NULL
            ORDER BY p.id
            LIMIT 10
            """
        )
    ).all()


def _is_offline_mode() -> bool:
    # Unit tests import migration modules outside Alembic's EnvironmentContext;
    # the proxy raises NameError there and should be treated as online.
    try:
        return context.is_offline_mode()
    except NameError:
        return False


def upgrade() -> None:
    # Offline SQL generation has no database connection to inspect.  The
    # precondition remains enforced on every online upgrade; offline output
    # can only emit the FK DDL and must be checked before execution.
    examples = (
        []
        if _is_offline_mode()
        else _orphaned_product_category_references(op.get_bind())
    )
    if examples:
        raise RuntimeError(
            "Cannot add products.category_id foreign key: "
            f"orphan reference(s) found; examples={examples}. "
            "Resolve these product references explicitly, then rerun the migration."
        )

    op.create_foreign_key(
        "fk_products_category_id_categories",
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_products_category_id_categories", "products", type_="foreignkey"
    )
